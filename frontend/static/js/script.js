// Global state
let token = localStorage.getItem('token') || '';
let restaurants = [];
let selectedRestaurant = '';
let visualizations = null;
let anomalies = [];
let epsDividendChart = null;
let exchangeRateRefreshInterval = null;

// Chart instances
let waterfallChart = null;
let revenueChart = null;
let expenseChart = null;
let trendsChart = null;
let detailedRevenueChart = null;
let companyFranchiseChart = null;
let profitabilityChart = null;

// Initialize the app when the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  const loginForm = document.getElementById('loginForm');
  if (loginForm) {
    loginForm.addEventListener('submit', handleLogin);
  }
  const registerForm = document.getElementById('registerForm');
  if (registerForm) {
    registerForm.addEventListener('submit', handleRegister);
  }
});


document.getElementById('uploadForm').addEventListener('submit', handleFileUpload);



async function initializeDashboard() {
  try {
    // Verify auth by making a simple request
    const response = await fetch('/api/verify-auth', {
      credentials: 'include'
    });
    
    if (!token) {
      window.location.href = '/login';
      return;
    }
    
  
  } catch (error) {
    console.error('Auth check failed:', error);
    window.location.href = '/login';
  }
}

// Navigation functions
function navigateTo(page) {
  window.location.href = `/${page}`;  
}

async function logout() {
  try {
    // Call backend logout endpoint
    const response = await fetch('/api/logout', {
      method: 'POST',
      credentials: 'include'
    });

    // Clear frontend state
    token = '';
    localStorage.removeItem('token');
    restaurants = [];
    visualizations = null;
    anomalies = [];

    // Redirect to login page
    window.location.href = '/login';
    
  } catch (error) {
    console.error('Logout error:', error);
    // Fallback redirect if logout fails
    window.location.href = '/login';
  }
}

// Auth functions
async function handleLogin(e) {
  e.preventDefault(); 
  
  const username = document.getElementById('username').value;
  const password = document.getElementById('password').value;

  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({
        username: username,
        password: password
      })
    });

    const data = await response.json();
    
    if (response.ok) {
      window.location.href = '/dashboard'; // Redirect to dashboard
    } else {
      alert(data.message || 'Login failed');
    }
  } catch (error) {
    console.error('Login error:', error);
    alert('Failed to connect to server');
  }
}

async function handleRegister(e) {
  e.preventDefault(); // This is CRUCIAL: It stops the form from refreshing the page.
  const username = document.getElementById('regUsername').value;
  const email = document.getElementById('regEmail').value;
  const password = document.getElementById('regPassword').value;

  try {
    const response = await fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password })
    });

    const data = await response.json();
    
    if (response.ok) {
      alert('Registration successful! Please login.');
      window.location.href = '/login'; // Redirect to login page
    } else {
      // Show error message from server
      const errorElement = document.getElementById('errorMessage');
      errorElement.textContent = data.message || 'Registration failed';
      errorElement.style.display = 'block';
    }
  } catch (error) {
    console.error('Registration error:', error);
    document.getElementById('errorMessage').textContent = 'Failed to connect to server';
    document.getElementById('errorMessage').style.display = 'block';
  }
}

// Dashboard functions
async function initializeDashboard() {
  if (!token) {
    window.location.href = 'index.html';
    return;
  }
}

console.log("Currency system initialized");
console.log("Current currency:", currentCurrency);
console.log("Exchange rate:", exchangeRate);


// Function to fetch exchange rate for specific currencies
async function fetchExchangeRate(fromCurrency = 'USD', toCurrency = null) {
  try {
    const targetCurrency = toCurrency || currentCurrency;
    console.log(`Fetching exchange rate from ${fromCurrency} to ${targetCurrency}`);
    
    const response = await fetch(`/api/exchange_rate?from=${fromCurrency}&to=${targetCurrency}`);
    
    if (response.ok) {
      const data = await response.json();
      exchangeRate = data.rate || 1500;
      exchangeRateLastUpdated = data.last_updated || new Date().toISOString();
      exchangeRateSource = data.source || 'unknown';
      
      console.log(`Exchange rate updated: 1 ${fromCurrency} = ${exchangeRate} ${targetCurrency} (source: ${exchangeRateSource})`);
      return data;
    } else {
      // Use default rate if API fails
      exchangeRate = fromCurrency === 'USD' && targetCurrency === 'NGN' ? 1500 : 1;
      exchangeRateLastUpdated = new Date().toISOString();
      exchangeRateSource = 'error_fallback';
      console.warn('Failed to fetch exchange rate, using default');
      return {rate: exchangeRate, last_updated: exchangeRateLastUpdated, source: exchangeRateSource};
    }
  } catch (error) {
    console.error('Error fetching exchange rate:', error);
    exchangeRate = fromCurrency === 'USD' && targetCurrency === 'NGN' ? 1500 : 1;
    exchangeRateLastUpdated = new Date().toISOString();
    exchangeRateSource = 'error_fallback';
    return {rate: exchangeRate, last_updated: exchangeRateLastUpdated, source: exchangeRateSource};
  }
}

async function initializeCurrencySystem() {
  try {
    // Set default currency
    currentCurrency = 'NGN';
    
    // Fetch the latest exchange rate (USD to NGN)
    await fetchExchangeRate('USD', 'NGN');
    
    // Update exchange rate info display
    updateExchangeRateInfo();
    
    // Set the selector to the current currency
    const selector = document.getElementById('currencySelector');
    if (selector) {
      selector.value = currentCurrency;
    }
    
  } catch (error) {
    console.error('Error initializing currency system:', error);
  }
}
// Clean up interval when page is unloaded
window.addEventListener('beforeunload', () => {
  if (exchangeRateRefreshInterval) {
    clearInterval(exchangeRateRefreshInterval);
  }
});

async function fetchVisualizations(restaurantId) {
    console.log("Fetching visualizations");
    try {
        const response = await fetch(
            `/api/visualizations/?restaurant_id=${restaurantId}`,
            { 
                credentials: 'include',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            }
        );
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        visualizations = data;
        anomalies = data.anomalies || [];
        
        // Update summary cards
        updateSummaryCards(data);
        
        // Update all charts
        updateCharts();
        
        // Check if we have data for new charts
        if (data.waterfall && data.waterfall.revenue > 0) {
            updateNewCharts(data);
        } else {
            handleMissingData();
        }
        
        updateAnomaliesTable();
        
    } catch (error) {
        console.error('Error fetching visualizations:', error);
        document.getElementById('anomaliesTable').innerHTML = 
            `<p class="error">Error loading data: ${error.message}</p>`;
        handleMissingData();
    }
}

async function handleFileUpload(e) {
  e.preventDefault();
  const fileInput = document.getElementById('fileInput');
  const file = fileInput.files[0];
  const submitButton = e.target.querySelector('button[type="submit"]');
  
  if (!file) {
    alert('Please select a file');
    return;
  }

  // Check file type
  if (!file.name.endsWith('.csv') && !file.name.endsWith('.xlsx')) {
    alert('Please select a CSV or Excel file');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  
  try {
    // Show loading state
    submitButton.disabled = true;
    submitButton.textContent = 'Uploading...';
    
    const response = await fetch('/api/upload', {
      method: 'POST',
      credentials: 'include',
      body: formData,
    });
    
    const data = await response.json();
    
    if (response.ok) {
      if (data.error_count > 0) {
        alert(`${data.message}\n\nErrors:\n${data.errors.join('\n')}`);
      } else {
        alert(data.message);
      }
      // Refresh visualizations with the restaurant_id from response
      await fetchVisualizations(data.restaurant_id);
    } else {
      alert(data.message || 'Upload failed');
    }
  } catch (error) {
    console.error('Upload error:', error);
    alert('Failed to upload file. Please try again.');
  } finally {
    // Reset button state
    submitButton.disabled = false;
    submitButton.textContent = 'Upload';
    // Clear file input
    fileInput.value = '';
  }
}

function formatCurrency(amount) {
    return '$' + amount.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function updateNewCharts(data) {
    // Check if we have data before creating charts
    const hasData = data.waterfall && data.waterfall.revenue > 0;
    
    if (hasData) {
        createDetailedRevenueChart(data);
        createCompanyFranchiseChart(data);
        createProfitabilityChart(data);
        createEPSDividendChart(data);
    } else {
        // Show "no data" messages for all charts
        showNoDataMessage('detailedRevenueChart');
        showNoDataMessage('companyFranchiseChart');
        showNoDataMessage('profitabilityChart');
        showNoDataMessage('epsDividendChart');
    }
}

function showNoDataMessage(chartId) {
    const container = document.getElementById(chartId)?.closest('.chart-container');
    if (container) {
        const existingMessage = container.querySelector('.no-data-message');
        if (!existingMessage) {
            const message = document.createElement('p');
            message.className = 'no-data-message';
            message.textContent = 'Upload data to see this chart';
            message.style.textAlign = 'center';
            message.style.padding = '20px';
            message.style.color = '#999';
            message.style.fontStyle = 'italic';
            container.appendChild(message);
        }
    }
}

function updateSummaryCards(data) {
  const revenue = data.waterfall.revenue;
  const expenses = data.waterfall.expenses;
  const netIncome = data.waterfall.net_cash;
  const profitMargin = revenue > 0 ? ((netIncome / revenue) * 100).toFixed(2) : 0;
  
  document.getElementById('totalRevenue').textContent = formatCurrency(revenue);
  document.getElementById('totalExpenses').textContent = formatCurrency(expenses);
  document.getElementById('netIncome').textContent = formatCurrency(netIncome);
  document.getElementById('profitMargin').textContent = `${profitMargin}%`;
  updateStatisticalSummary(data);
}

document.getElementById('registerForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const formData = {
        username: document.getElementById('regUsername').value,
        email: document.getElementById('regEmail').value,
        password: document.getElementById('regPassword').value
    };
    
    fetch('/register', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.message) {
            alert(data.message);
            window.location.href = '/login';
        }
    })
    .catch(error => console.error('Error:', error));
});



function updateCharts() {
    if (typeof ChartDataLabels !== 'undefined') {
        Chart.register(ChartDataLabels);
    }
    
    // Waterfall Chart
    if (waterfallChart) waterfallChart.destroy();
    const waterfallCtx = document.getElementById('waterfallChart').getContext('2d');
    waterfallChart = new Chart(waterfallCtx, {
        type: 'bar',
        data: {
            labels: ['Revenue', 'Expenses', 'Net Cash'],
            datasets: [{
                label: 'Amount ($)',
                data: [
                    visualizations.waterfall.revenue,
                    -visualizations.waterfall.expenses,
                    visualizations.waterfall.net_cash,
                ],
                backgroundColor: [
                    'rgba(75, 192, 192, 0.6)',
                    'rgba(255, 99, 132, 0.6)',
                    'rgba(54, 162, 235, 0.6)',
                ],
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            aspectRatio: 2,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) label += ': ';
                            label += '$' + Math.abs(context.raw).toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                            return label;
                        }
                    }
                },
                datalabels: {
                    color: '#000',
                    anchor: 'end',
                    align: 'top',
                    formatter: function(value) {
                        return '$' + Math.abs(value).toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        });
                    },
                    font: {
                        weight: 'bold',
                        size: 10
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '$' + Math.abs(value).toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                }
            }
        },
        plugins: [ChartDataLabels]
    });

    // Pie Charts (Revenue and Expense) - Common options
    const pieOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            tooltip: {
                callbacks: {
                    label: function(context) {
                        const label = context.label || '';
                        const value = '$' + context.raw.toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        });
                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                        const percentage = Math.round((context.parsed / total) * 100) + '%';
                        return `${label}: ${value} (${percentage})`;
                    }
                }
            },
            datalabels: {
                color: '#fff',
                font: {
                    weight: 'bold',
                    size: 12
                },
                formatter: function(value, context) {
                    const dataset = context.chart.data.datasets[0];
                    const total = dataset.data.reduce((acc, data) => acc + data, 0);
                    const percentage = Math.round((value / total) * 100) + '%';
                    return percentage;
                }
            }
        }
    };

    // Revenue Chart
    if (revenueChart) revenueChart.destroy();
    const revenueCtx = document.getElementById('revenueChart').getContext('2d');
    
    const revenueBreakdown = visualizations.revenue_breakdown || {};
    
    revenueChart = new Chart(revenueCtx, {
        type: 'pie',
        data: {
            labels: Object.keys(revenueBreakdown),
            datasets: [{
                data: Object.values(revenueBreakdown),
                backgroundColor: [
                    'rgba(255, 99, 132, 0.8)',
                    'rgba(54, 162, 235, 0.8)',
                    'rgba(255, 206, 86, 0.8)',
                    'rgba(75, 192, 192, 0.8)',
                    'rgba(153, 102, 255, 0.8)',
                    'rgba(255, 159, 64, 0.8)',
                    'rgba(199, 199, 199, 0.8)',
                ],
                borderColor: [
                    'rgba(255, 99, 132, 1)',
                    'rgba(54, 162, 235, 1)',
                    'rgba(255, 206, 86, 1)',
                    'rgba(75, 192, 192, 1)',
                    'rgba(153, 102, 255, 1)',
                    'rgba(255, 159, 64, 1)',
                    'rgba(199, 199, 199, 1)',
                ],
                borderWidth: 1
            }]
        },
        options: pieOptions,
        plugins: [ChartDataLabels]
    });

    // Expense Chart
    if (expenseChart) expenseChart.destroy();
    const expenseCtx = document.getElementById('expenseChart').getContext('2d');
    
    const expenseBreakdown = visualizations.expense_breakdown || {};
    
    expenseChart = new Chart(expenseCtx, {
        type: 'pie',
        data: {
            labels: Object.keys(expenseBreakdown),
            datasets: [{
                data: Object.values(expenseBreakdown),
                backgroundColor: [
                    'rgba(255, 99, 132, 0.8)',
                    'rgba(54, 162, 235, 0.8)',
                    'rgba(255, 206, 86, 0.8)',
                    'rgba(75, 192, 192, 0.8)',
                    'rgba(153, 102, 255, 0.8)',
                    'rgba(255, 159, 64, 0.8)',
                    'rgba(199, 199, 199, 0.8)',
                ],
                borderColor: [
                    'rgba(255, 99, 132, 1)',
                    'rgba(54, 162, 235, 1)',
                    'rgba(255, 206, 86, 1)',
                    'rgba(75, 192, 192, 1)',
                    'rgba(153, 102, 255, 1)',
                    'rgba(255, 159, 64, 1)',
                    'rgba(199, 199, 199, 1)',
                ],
                borderWidth: 1
            }]
        },
        options: pieOptions,
        plugins: [ChartDataLabels]
    });

    // Trends Chart
    if (trendsChart) trendsChart.destroy();
    const trendsCtx = document.getElementById('trendsChart').getContext('2d');
    
    const monthlyTrends = visualizations.monthly_trends || { revenue: {}, expense: {} };
    
    trendsChart = new Chart(trendsCtx, {
        type: 'line',
        data: {
            labels: Object.keys(monthlyTrends.revenue),
            datasets: [
                {
                    label: 'Revenue ($)',
                    data: Object.values(monthlyTrends.revenue),
                    borderColor: 'rgba(75, 192, 192, 1)',
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    fill: true,
                    tension: 0.3,
                },
                {
                    label: 'Expenses ($)',
                    data: Object.values(monthlyTrends.expense),
                    borderColor: 'rgba(255, 99, 132, 1)',
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    fill: true,
                    tension: 0.3,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': $' + context.raw.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                },
                datalabels: {
                    color: '#000',
                    anchor: 'end',
                    align: 'top',
                    formatter: function(value) {
                        return '$' + value.toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        });
                    },
                    font: {
                        weight: 'bold',
                        size: 10
                    },
                    display: function(context) {
                        // Only show labels for every other data point to avoid clutter
                        return context.dataIndex % 2 === 0;
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '$' + value.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                }
            }
        },
        plugins: [ChartDataLabels]
    });
}

// 1. Detailed Revenue Breakdown Chart
function createDetailedRevenueChart(data) {
    if (detailedRevenueChart) detailedRevenueChart.destroy();
    
    const ctx = document.getElementById('detailedRevenueChart');
    if (!ctx) return;
    
    // CORRECTED: Use revenue_breakdown instead of revenueData
    const revenueBreakdown = data.revenue_breakdown || {};
    
    // Check if we have data
    if (Object.keys(revenueBreakdown).length === 0 || Object.values(revenueBreakdown).reduce((sum, val) => sum + val, 0) === 0) {
        showNoDataMessage('detailedRevenueChart');
        return;
    }
    
    const chartCtx = ctx.getContext('2d');
    detailedRevenueChart = new Chart(chartCtx, {
        type: 'bar',
        data: {
            labels: Object.keys(revenueBreakdown),
            datasets: [{
                label: 'Revenue ($)',
                data: Object.values(revenueBreakdown),
                backgroundColor: 'rgba(54, 162, 235, 0.7)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return '$' + context.raw.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                },
                datalabels: {
                    color: '#000',
                    anchor: 'end',
                    align: 'top',
                    formatter: function(value) {
                        return '$' + value.toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        });
                    },
                    font: {
                        weight: 'bold',
                        size: 10
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '$' + value.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                }
            }
        },
        plugins: [ChartDataLabels]
    });
}

function createCompanyFranchiseChart(data) {
    if (companyFranchiseChart) companyFranchiseChart.destroy();
    
    const ctx = document.getElementById('companyFranchiseChart');
    if (!ctx) return;
    
    // Use data from backend
    const companyFranchiseData = data.company_vs_franchise || {};
    
    // Check if we have data
    if (Object.values(companyFranchiseData).reduce((sum, val) => sum + val, 0) === 0) {
        showNoDataMessage('companyFranchiseChart');
        return;
    }
    
    const chartCtx = ctx.getContext('2d');
    companyFranchiseChart = new Chart(chartCtx, {
        type: 'bar',
        data: {
            labels: Object.keys(companyFranchiseData),
            datasets: [{
                label: 'Revenue ($)',
                data: Object.values(companyFranchiseData),
                backgroundColor: [
                    'rgba(54, 162, 235, 0.7)',
                    'rgba(255, 99, 132, 0.7)'
                ],
                borderColor: [
                    'rgba(54, 162, 235, 1)',
                    'rgba(255, 99, 132, 1)'
                ],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return '$' + context.raw.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                },
                datalabels: {
                    color: '#000',
                    anchor: 'end',
                    align: 'top',
                    formatter: function(value) {
                        return '$' + value.toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        });
                    },
                    font: {
                        weight: 'bold',
                        size: 10
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '$' + value.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                }
            }
        },
        plugins: [ChartDataLabels]
    });
}

function createProfitabilityChart(data) {
    if (profitabilityChart) profitabilityChart.destroy();
    
    const ctx = document.getElementById('profitabilityChart');
    if (!ctx) return;
    
    // Calculate profitability metrics from your actual data
    const revenue = data.waterfall.revenue || 0;
    const expenses = data.waterfall.expenses || 0;
    const netIncome = data.waterfall.net_cash || 0;
    
    // Check if we have data
    if (revenue === 0 && expenses === 0 && netIncome === 0) {
        showNoDataMessage('profitabilityChart');
        return;
    }
    
    // Calculate operating income (simplified as revenue - operating expenses)
    const operatingIncome = revenue - expenses;
    
    // Calculate profit margin
    const profitMargin = revenue > 0 ? (netIncome / revenue) * 100 : 0;
    
    const profitabilityData = {
        'Operating Income': operatingIncome,
        'Net Income': netIncome,
        'Profit Margin (%)': parseFloat(profitMargin.toFixed(2))
    };
    
    const chartCtx = ctx.getContext('2d');
    profitabilityChart = new Chart(chartCtx, {
        type: 'bar',
        data: {
            labels: Object.keys(profitabilityData),
            datasets: [{
                label: 'Amount ($)',
                data: Object.values(profitabilityData),
                backgroundColor: [
                    'rgba(75, 192, 192, 0.7)',
                    'rgba(54, 162, 235, 0.7)',
                    'rgba(255, 159, 64, 0.7)'
                ],
                borderColor: [
                    'rgba(75, 192, 192, 1)',
                    'rgba(54, 162, 235, 1)',
                    'rgba(255, 159, 64, 1)'
                ],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            if (context.label === 'Profit Margin (%)') {
                                return `${context.label}: ${context.raw}%`;
                            }
                            return '$' + context.raw.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                },
                datalabels: {
                    color: '#000',
                    anchor: 'end',
                    align: 'top',
                    formatter: function(value, context) {
                        if (context.chart.data.labels[context.dataIndex] === 'Profit Margin (%)') {
                            return value + '%';
                        }
                        return '$' + value.toLocaleString('en-US', {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2
                        });
                    },
                    font: {
                        weight: 'bold',
                        size: 10
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '$' + value.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                }
            }
        },
        plugins: [ChartDataLabels]
    });
}

// 4. EPS & Dividend Trends Chart
function createEPSDividendChart(data) {
    if (epsDividendChart) epsDividendChart.destroy();
    
    const ctx = document.getElementById('epsDividendChart');
    if (!ctx) return;
    
    // Check if we have monthly data
    const monthlyTrends = data.monthly_trends || {};
    const hasMonthlyData = Object.keys(monthlyTrends.revenue || {}).length > 0;
    
    if (!hasMonthlyData) {
        showNoDataMessage('epsDividendChart');
        return;
    }
    
    const chartCtx = ctx.getContext('2d');
    
    // Use data from backend if available, otherwise calculate
    const epsDividendData = data.eps_dividend || {};
    
    const months = Object.keys(monthlyTrends.revenue || {});
    let epsValues = [];
    let dividendValues = [];
    
    // Calculate EPS and dividends from monthly data
    months.forEach(month => {
        const revenue = monthlyTrends.revenue[month] || 0;
        const expense = monthlyTrends.expense[month] || 0;
        const netIncome = revenue - expense;
        
        // Simplified calculations - adjust these formulas as needed
        epsValues.push(netIncome > 0 ? (netIncome / 1000) : 0); // EPS calculation
        dividendValues.push(netIncome > 0 ? (netIncome * 0.2) : 0); // 20% dividend payout
    });
    
    epsDividendChart = new Chart(chartCtx, {
        type: 'line',
        data: {
            labels: months,
            datasets: [
                {
                    label: 'EPS ($)',
                    data: epsValues,
                    borderColor: 'rgba(54, 162, 235, 1)',
                    backgroundColor: 'rgba(54, 162, 235, 0.2)',
                    fill: false,
                    tension: 0.3,
                },
                {
                    label: 'Dividends ($)',
                    data: dividendValues,
                    borderColor: 'rgba(255, 99, 132, 1)',
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    fill: false,
                    tension: 0.3,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: $${context.raw.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            })}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '$' + value.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            });
                        }
                    }
                }
            }
        }
    });
}

function updateAnomaliesTable() {
    const tableContainer = document.getElementById('anomaliesTable');
    tableContainer.innerHTML = ''; // Clear previous anomalies
    
    if (!anomalies || anomalies.length === 0) {
        tableContainer.innerHTML = '<p>No anomalies detected</p>';
        return;
    }
    
    const table = document.createElement('table');
    table.className = 'anomalies-table';
    
    // Create header
    const thead = document.createElement('thead');
    thead.innerHTML = `
        <tr>
            <th>Date</th>
            <th>Category</th>
            <th>Type</th>
            <th>Amount ($)</th>
            <th>Reason</th>
        </tr>
    `;
    table.appendChild(thead);
    
    // Create body
    const tbody = document.createElement('tbody');
    anomalies.forEach(anomaly => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${new Date(anomaly.date).toLocaleDateString()}</td>
            <td>${anomaly.category}</td>
            <td>${anomaly.type}</td>
            <td>$${parseFloat(anomaly.amount).toLocaleString('en-NG', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
            <td>${anomaly.reason}</td>
        `;
        tbody.appendChild(row);
    });
    table.appendChild(tbody);
    tableContainer.appendChild(table);
}

// Function to update statistical summary cards
function updateStatisticalSummary(data) {
  const stats = data.statistical_summary || {};
  
  // Use backend data, otherwise calculate locally
  const avgMonthlyRevenue = stats.avg_monthly_revenue || 
    (Object.values(data.monthly_trends?.revenue || {}).reduce((sum, val) => sum + val, 0) / 
    Object.keys(data.monthly_trends?.revenue || {}).length || 0);
  
  const revenueGrowthRate = stats.revenue_growth_rate || 0;
  const expenseToRevenue = stats.expense_to_revenue_ratio || 
    ((data.waterfall.expenses / data.waterfall.revenue) * 100) || 0;
  
  const anomalyPercentage = stats.anomaly_percentage || 
    ((data.anomalies.length / (data.anomalies.length + 100)) * 100) || 0;
  
  // Update the DOM elements
  document.getElementById('avgMonthlyRevenue').textContent = formatCurrency(avgMonthlyRevenue);
  document.getElementById('revenueGrowthRate').textContent = `${revenueGrowthRate.toFixed(2)}%`;
  document.getElementById('expenseToRevenue').textContent = `${expenseToRevenue.toFixed(2)}%`;
  document.getElementById('anomalyPercentage').textContent = `${anomalyPercentage.toFixed(2)}%`;
}

async function handleFileUpload(e) {
  e.preventDefault();
  const fileInput = document.getElementById('fileInput');
  const file = fileInput.files[0];
  
  if (!file) {
    alert('Please select a file');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  
  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      credentials: 'include',  // Important for cookies
      body: formData,
    });
    
    const data = await response.json();
    if (response.ok) {
      alert(data.message);
      // Refresh visualizations with the restaurant_id from response
      await fetchVisualizations(data.restaurant_id);
    } else {
      alert(data.message);
    }
  } catch (error) {
    console.error('Upload error:', error);
    alert('Failed to upload file');
  }
}

// function to handle missing elements
function ensureAllElementsExist() {
  // Create missing chart containers 
  const chartIds = [
    'waterfallChart', 'revenueChart', 'expenseChart', 'trendsChart',
    'detailedRevenueChart', 'companyFranchiseChart', 'profitabilityChart', 
      'epsDividendChart'
  ];
  
  chartIds.forEach(chartId => {
    if (!document.getElementById(chartId)) {
      console.warn(`Chart element ${chartId} not found, creating placeholder`);
    }
  });
  
  // Ensure summary cards exist
  const summaryIds = [
    'totalRevenue', 'totalExpenses', 'netIncome', 'profitMargin',
    'avgMonthlyRevenue', 'revenueGrowthRate', 'expenseToRevenue', 'anomalyPercentage'
  ];
  
  summaryIds.forEach(summaryId => {
    if (!document.getElementById(summaryId)) {
      console.warn(`Summary element ${summaryId} not found`);
    }
  });
}

async function generateServerReport() {
    ensureAllElementsExist();
    const loadingElement = document.getElementById('reportLoading');
    if (loadingElement) {
        loadingElement.style.display = 'flex';
    }

    try {
        // First get the user's restaurant
        const restaurantRes = await fetch('/api/restaurants', {
            credentials: 'include'
        });
        
        if (!restaurantRes.ok) {
            throw new Error('Failed to get restaurant data');
        }
        
        const restaurants = await restaurantRes.json();
        if (restaurants.length === 0) {
            throw new Error('No restaurant found');
        }
        
        // Use the first restaurant
        const restaurantId = restaurants[0].id;
        
        // Get current visualizations data
        if (!visualizations) {
            await fetchVisualizations(restaurantId);
        }
        
        // Capture all chart images (REMOVED cashFlowAnalysisChart)
        const chartImages = {};
        const chartIds = [
            'waterfallChart', 'revenueChart', 'expenseChart', 'trendsChart',
            'detailedRevenueChart', 'companyFranchiseChart', 'profitabilityChart', 
            'epsDividendChart'  // Removed: 'cashFlowAnalysisChart'
        ];
        
        for (const chartId of chartIds) {
            const canvas = document.getElementById(chartId);
            if (canvas) {
                // Use html2canvas for better rendering
                const chartContainer = canvas.closest('.chart-container');
                if (chartContainer) {
                    try {
                        const chartImage = await html2canvas(chartContainer, {
                            backgroundColor: '#FFFFFF',
                            scale: 2 // Higher resolution for PDF
                        });
                        chartImages[chartId] = chartImage.toDataURL('image/png');
                    } catch (error) {
                        console.error(`Error capturing ${chartId}:`, error);
                        // Fallback to just the canvas
                        chartImages[chartId] = canvas.toDataURL('image/png');
                    }
                } else {
                    chartImages[chartId] = canvas.toDataURL('image/png');
                }
            }
        }    
    // Capture summary cards
    const summaryCards = document.querySelector('.summary-cards');
    let summaryCardsImage = '';
    if (summaryCards) {
      try {
        const summaryCanvas = await html2canvas(summaryCards, {
          backgroundColor: '#FFFFFF',
          scale: 2
        });
        summaryCardsImage = summaryCanvas.toDataURL('image/png');
      } catch (error) {
        console.error('Error capturing summary cards:', error);
      }
    }
    
    // Capture statistical summary cards
    const statisticalSummary = document.querySelector('.statistical-summary');
    let statisticalSummaryImage = '';
    if (statisticalSummary) {
      try {
        const statisticalCanvas = await html2canvas(statisticalSummary, {
          backgroundColor: '#FFFFFF',
          scale: 2
        });
        statisticalSummaryImage = statisticalCanvas.toDataURL('image/png');
      } catch (error) {
        console.error('Error capturing statistical summary:', error);
      }
    }
    
    // Capture anomalies table
    const anomaliesTable = document.getElementById('anomaliesTable');
    let anomaliesTableHTML = '';
    if (anomaliesTable) {
      anomaliesTableHTML = anomaliesTable.innerHTML;
    }
    
    // Capture summary cards values as text
    const summaryData = {
      totalRevenue: document.getElementById('totalRevenue')?.textContent || '$0.00',
      totalExpenses: document.getElementById('totalExpenses')?.textContent || '$0.00',
      netIncome: document.getElementById('netIncome')?.textContent || '$0.00',
      profitMargin: document.getElementById('profitMargin')?.textContent || '0%',
      avgMonthlyRevenue: document.getElementById('avgMonthlyRevenue')?.textContent || '$0.00',
      revenueGrowthRate: document.getElementById('revenueGrowthRate')?.textContent || '0%',
      expenseToRevenue: document.getElementById('expenseToRevenue')?.textContent || '0%',
      anomalyPercentage: document.getElementById('anomalyPercentage')?.textContent || '0%'
    };
    
    // Generate comprehensive report
    const response = await fetch('/api/generate_report', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify({
        restaurant_id: restaurantId,
        report_type: 'comprehensive',
        visualizations: visualizations,
        anomalies: anomalies,
        currency: currency,
        chart_images: chartImages,
        summary_cards_image: summaryCardsImage,
        statistical_summary_image: statisticalSummaryImage,
        anomalies_table: anomaliesTableHTML,
        summary_data: summaryData
      })
    });
    
    if (response.ok) {
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `comprehensive_report_${new Date().toISOString().split('T')[0]}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } else {
      const errorData = await response.json();
      throw new Error(errorData.message || 'Failed to generate report');
    }
  } catch (error) {
    console.error('Error generating report:', error);
    alert(error.message || 'Failed to generate report');
  }finally {
    if (loadingElement) {
      loadingElement.style.display = 'none';
    }
  }
}
