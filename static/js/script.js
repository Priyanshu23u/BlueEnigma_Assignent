// Global variables
let currentTab = 'chat';
let network = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    showTab('chat');
});

// Tab switching
function showTab(tabName, event) {
    currentTab = tabName;
    
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    if (event && event.target) {
        const clickedBtn = event.target.closest('.nav-btn');
        if (clickedBtn) {
            clickedBtn.classList.add('active');
        }
    } else {
        const targetBtn = Array.from(document.querySelectorAll('.nav-btn'))
            .find(btn => btn.textContent.toLowerCase().includes(tabName));
        if (targetBtn) {
            targetBtn.classList.add('active');
        }
    }
    
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`${tabName}-tab`);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }
    
    if (tabName === 'graph') {
        // Force resize and re-render after tab is visible
        setTimeout(() => {
            if (network) {
                network.redraw();
                network.fit();
            } else {
                initializeNeo4jViz();
            }
        }, 100);
    }
}

// Chat functions
function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

function quickQuery(query) {
    document.getElementById('chatInput').value = query;
    sendMessage();
}

async function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    
    if (!message) return;
    
    // Disable input
    input.disabled = true;
    document.getElementById('sendBtn').disabled = true;
    
    // Add user message to chat
    addMessage(message, 'user');
    input.value = '';
    
    // Show loading
    showLoading(true);
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message })
        });
        
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        
        const data = await response.json();
        
        // Add bot response
        addMessage(data.response, 'bot');
        
        // Optionally show matched nodes
        if (data.graph_nodes && data.graph_nodes.length > 0) {
            addContextInfo(data.matches, data.graph_nodes);
        }
        
    } catch (error) {
        console.error('Error:', error);
        addMessage('Sorry, I encountered an error. Please try again.', 'bot');
    } finally {
        showLoading(false);
        input.disabled = false;
        document.getElementById('sendBtn').disabled = false;
        input.focus();
    }
}

function addMessage(text, sender) {
    const messagesContainer = document.getElementById('chatMessages');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}-message`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = sender === 'bot' 
        ? '<i class="fas fa-robot"></i>' 
        : '<i class="fas fa-user"></i>';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    // Parse markdown-style formatting
    const formattedText = formatMessageText(text);
    content.innerHTML = formattedText;
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    messagesContainer.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function formatMessageText(text) {
    // Basic markdown formatting
    let formatted = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/\n/g, '<br>')
        .replace(/\[Node (\d+)\]/g, '<span class="node-ref" onclick="showNodeInGraph(\'$1\')">Node $1</span>');
    
    // Convert numbered lists
    formatted = formatted.replace(/(\d+)\.\s/g, '<br>$1. ');
    
    return formatted;
}

function addContextInfo(matches, nodeIds) {
    const messagesContainer = document.getElementById('chatMessages');
    
    const contextDiv = document.createElement('div');
    contextDiv.className = 'message bot-message';
    contextDiv.innerHTML = `
        <div class="message-avatar">
            <i class="fas fa-info-circle"></i>
        </div>
        <div class="message-content">
            <p><strong>Context Used:</strong></p>
            <p>📊 Found ${matches.length} relevant results from ${nodeIds.length} graph nodes</p>
            <button class="quick-btn" onclick="showNodesInGraph(${JSON.stringify(nodeIds).replace(/"/g, '&quot;')})">
                <i class="fas fa-project-diagram"></i> View in Graph
            </button>
        </div>
    `;
    
    messagesContainer.appendChild(contextDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showLoading(show) {
    const overlay = document.getElementById('loadingOverlay');
    if (show) {
        overlay.classList.add('active');
    } else {
        overlay.classList.remove('active');
    }
}

// Neo4j Graph Visualization Functions
async function initializeNeo4jViz() {
    console.log("Initializing graph visualization...");
    showLoading(true);
    
    try {
        console.log("Fetching initial graph data...");
        const response = await fetch('/api/graph/initial');
        console.log("Response status:", response.status);
        
        const data = await response.json();
        console.log("Graph data received:", data);
        
        if (data.nodes && data.nodes.length > 0) {
            console.log(`Rendering ${data.nodes.length} nodes and ${data.edges.length} edges`);
            renderCustomGraph(data.nodes, data.edges);
        } else {
            console.log("No graph data available");
            document.getElementById('neo4jViz').innerHTML = `
                <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b;">
                    <div style="text-align: center;">
                        <i class="fas fa-project-diagram" style="font-size: 3rem; margin-bottom: 1rem;"></i>
                        <p><strong>No graph data available</strong></p>
                        <p style="font-size: 0.9rem; margin-top: 0.5rem;">
                            The database returned no nodes. Please check if Neo4j has data.
                        </p>
                        <button class="control-btn" onclick="location.reload()" style="margin-top: 1rem;">
                            <i class="fas fa-redo"></i> Retry
                        </button>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        console.error("Error loading graph:", error);
        document.getElementById('neo4jViz').innerHTML = `
            <div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #64748b;">
                <div style="text-align: center;">
                    <i class="fas fa-exclamation-triangle" style="font-size: 3rem; margin-bottom: 1rem; color: #ef4444;"></i>
                    <p><strong>Failed to load graph</strong></p>
                    <p style="font-size: 0.9rem; margin-top: 0.5rem;">
                        Error: ${error.message}
                    </p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem; color: #94a3b8;">
                        Check the browser console (F12) for details
                    </p>
                    <button class="control-btn" onclick="location.reload()" style="margin-top: 1rem;">
                        <i class="fas fa-redo"></i> Retry
                    </button>
                </div>
            </div>
        `;
    } finally {
        showLoading(false);
    }
}


function searchNode() {
    const nodeId = document.getElementById('nodeSearchInput').value.trim();
    if (!nodeId) {
        alert('Please enter a node ID');
        return;
    }
    
    showNodeInGraph(nodeId);
}

function handleGraphSearch(event) {
    if (event.key === 'Enter') {
        searchNode();
    }
}

async function showNodeInGraph(nodeId) {
    // Switch to graph tab properly
    currentTab = 'graph';
    
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelectorAll('.nav-btn')[1].classList.add('active');
    
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Show graph tab
    document.getElementById('graph-tab').classList.add('active');
    
    showLoading(true);
    
    try {
        const response = await fetch(`/api/graph/${nodeId}`);
        const data = await response.json();
        
        if (data.error) {
            alert(`Error: ${data.error}`);
            return;
        }
        
        if (data.nodes.length === 0) {
            alert(`No data found for node ID: ${nodeId}`);
            return;
        }
        
        // Render graph
        renderCustomGraph(data.nodes, data.edges);
        
    } catch (error) {
        console.error('Error fetching graph:', error);
        alert('Failed to load graph data. Please check if the node ID exists.');
    } finally {
        showLoading(false);
    }
}

function showNodesInGraph(nodeIds) {
    if (nodeIds && nodeIds.length > 0) {
        showNodeInGraph(nodeIds[0]);
    }
}

function renderCustomGraph(nodes, edges) {
    console.log("Rendering graph with", nodes.length, "nodes and", edges.length, "edges");
    
    const container = document.getElementById('neo4jViz');
    
    if (!container || typeof vis === 'undefined' || !nodes || nodes.length === 0) {
        return;
    }
    
    // Clear container
    container.innerHTML = '';
    
    // Prepare node data with better label positioning
    const nodeData = nodes.map(node => ({
        id: String(node.id),
        label: String(node.label || node.id),
        title: `<strong>${node.label || node.id}</strong><br>Type: ${node.type || 'Unknown'}<br>ID: ${node.id}`,
        color: {
            background: getNodeColor(node.type),
            border: '#1e293b',
            highlight: {
                background: getNodeColor(node.type),
                border: '#0f172a'
            }
        },
        font: { 
            color: '#1e293b',
            size: 12,
            face: 'Poppins',
            multi: false,
            bold: {
                size: 14
            }
        },
        shape: 'dot',
        size: 30,
        borderWidth: 2,
        chosen: {
            node: function(values, id, selected, hovering) {
                if (selected || hovering) {
                    values.size = 35;
                    values.borderWidth = 3;
                }
            }
        }
    }));
    
    // Prepare edge data - hide labels by default to reduce clutter
    // Prepare edge data with cleaner labels
const edgeData = edges.map((edge, idx) => ({
    id: idx,
    from: String(edge.from),
    to: String(edge.to),
    label: edge.label || '',  // Show the relationship label
    title: `Relationship: ${edge.label || 'Related'}`,
    arrows: { 
        to: { 
            enabled: true, 
            scaleFactor: 0.6 
        } 
    },
    color: { 
        color: '#94a3b8',
        highlight: '#1e293b',
        hover: '#475569'
    },
    width: 1.5,
    font: {
        size: 15,
        color: '#64748b',
        face: 'Poppins',
        strokeWidth: 2,
        strokeColor: '#ffffff',
        align: 'middle',
        background: 'rgba(255, 255, 255, 0.8)',
        padding: 2
    },
    smooth: {
        type: 'continuous',
        roundness: 0.5
    },
    chosen: {
        edge: function(values, id, selected, hovering) {
            if (hovering) {
                values.width = 3;
            }
        }
    }
}));

    
    const data = {
        nodes: new vis.DataSet(nodeData),
        edges: new vis.DataSet(edgeData)
    };
    
    const options = {
        nodes: {
            shape: 'dot',
            size: 30,
            font: {
                size: 112,
                color: '#1e293b',
                face: 'Poppins',
                strokeWidth: 3,
                strokeColor: '#ffffff',
                align: 'center'
            },
            borderWidth: 2,
            shadow: {
                enabled: true,
                color: 'rgba(0,0,0,0.15)',
                size: 8,
                x: 2,
                y: 2
            }
        },
        edges: {
    width: 1.5,
    shadow: {
        enabled: true,
        color: 'rgba(0,0,0,0.1)',
        size: 50
    },
    font: {
        size: 10,
        color: '#64748b',
        face: 'Poppins',
        strokeWidth: 2,
        strokeColor: '#ffffff',
        align: 'middle',
        background: 'rgba(255, 255, 255, 0.8)'
    },
    smooth: {
        type: 'continuous',
        roundness: 0.5
    }
},

        physics: {
            enabled: true,
            stabilization: {
                enabled: true,
                iterations: 150,
                updateInterval: 25,
                fit: true
            },
            barnesHut: {
                gravitationalConstant: -3000,
                centralGravity: 0.1,
                springLength: 300,
                springConstant: 0.04,
                damping: 0.09,
                avoidOverlap: 0.5
            },
            maxVelocity: 50,
            minVelocity: 0.1,
            solver: 'barnesHut'
        },
        interaction: {
            hover: true,
            tooltipDelay: 100,
            zoomView: true,
            dragView: true,
            navigationButtons: true,
            keyboard: {
                enabled: true,
                bindToWindow: false
            },
            multiselect: false,
            hideEdgesOnDrag: false,
            hideEdgesOnZoom: false
        },
        layout: {
            improvedLayout: true,
            hierarchical: false,
            randomSeed: 42
        }
    };
    
    // Destroy previous network
    if (network) {
        network.destroy();
        network = null;
    }
    
    try {
        network = new vis.Network(container, data, options);
        
        // Event handlers
        network.on('click', function(params) {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                console.log('Clicked node:', nodeId);
            }
        });
        
        network.on('hoverNode', function(params) {
            container.style.cursor = 'pointer';
        });
        
        network.on('blurNode', function(params) {
            container.style.cursor = 'default';
        });
        
        network.on('stabilizationIterationsDone', function() {
            console.log("Stabilization complete");
            network.setOptions({ physics: { enabled: false } });
            
            // Fit view with padding
            network.fit({
                animation: {
                    duration: 1000,
                    easingFunction: 'easeInOutQuad'
                },
                padding: 50
            });
        });
        
        network.on('stabilizationProgress', function(params) {
            const progress = Math.round((params.iterations / params.total) * 100);
            if (progress % 20 === 0) {
                console.log(`Stabilizing: ${progress}%`);
            }
        });
        
    } catch (error) {
        console.error("Error creating network:", error);
    }
}


function getNodeColor(type) {
    const colors = {
        'City': '#2563eb',
        'Attraction': '#10b981',
        'Hotel': '#f59e0b',
        'Restaurant': '#ef4444',
        'Activity': '#8b5cf6',
        'Region': '#06b6d4',
        'Beach': '#14b8a6',
        'Museum': '#a855f7'
    };
    return colors[type] || '#64748b';
}

function resetGraph() {
    if (network) {
        network.fit({
            animation: {
                duration: 1000,
                easingFunction: 'easeInOutQuad'
            }
        });
    } else {
        initializeNeo4jViz();
    }
}

// Auto-scroll on new messages
const observer = new MutationObserver(() => {
    const messages = document.getElementById('chatMessages');
    if (messages) {
        messages.scrollTop = messages.scrollHeight;
    }
});

const messagesContainer = document.getElementById('chatMessages');
if (messagesContainer) {
    observer.observe(messagesContainer, { childList: true });
}

// Force graph resize when tab is shown
