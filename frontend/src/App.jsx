import React, { useState, useEffect } from 'react';

// --- MOCK FIREBASE DATA ---
// Represents docs in Firestore where confidence_score < 0.80
const mockQueue = [
  {
    id: "doc-10394",
    document_type: "INVOICE",
    gcs_uri: "gs://raw-documents-pipeline/sample_invoice_acme.pdf",
    timestamp: "2026-03-15T14:22:00Z",
    overall_score: 0.72,
    extracted_data: {
      "Vendor Name": "Acme Corp",
      "Total Amount": "$4,520.00",
      "Date": "2026-03-10",
      "Tax ID": "MISSING"
    },
    confidence_scores: {
      "Vendor Name": 0.95,
      "Total Amount": 0.90,
      "Date": 0.85,
      "Tax ID": 0.20
    }
  },
  {
    id: "doc-10395",
    document_type: "CONTRACT",
    gcs_uri: "gs://raw-documents-pipeline/vendor_agreement_v2.pdf",
    timestamp: "2026-03-15T15:01:30Z",
    overall_score: 0.65,
    extracted_data: {
      "Contract Type": "Vendor Agreement",
      "Signatures Present": "false",
      "Effective Date": "Pending"
    },
    confidence_scores: {
      "Contract Type": 0.85,
      "Signatures Present": 0.50,
      "Effective Date": 0.60
    }
  }
];

export default function App() {
  const [queue, setQueue] = useState(mockQueue);
  const [activeDoc, setActiveDoc] = useState(mockQueue[0]);
  const [editedFields, setEditedFields] = useState({});

  useEffect(() => {
    if (activeDoc) {
      setEditedFields(activeDoc.extracted_data);
    }
  }, [activeDoc]);

  const handleFieldChange = (key, value) => {
    setEditedFields(prev => ({ ...prev, [key]: value }));
  };

  const handleApprove = () => {
    // In a real app, write back to Firestore and trigger pubsub compliance topic
    console.log("Approved payload:", { ...activeDoc, extracted_data: editedFields });
    // Remove from queue locally for demo
    setQueue(prev => prev.filter(d => d.id !== activeDoc.id));
    setActiveDoc(queue.length > 1 ? queue[1] : null);
  };

  const handleReject = () => {
    console.log("Rejected. Routing to dead-letter or human ops.");
    setQueue(prev => prev.filter(d => d.id !== activeDoc.id));
    setActiveDoc(queue.length > 1 ? queue[1] : null);
  };

  return (
    <div className="min-h-screen bg-background relative overflow-hidden flex">
      {/* Background glowing orbs */}
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-primary/20 rounded-full blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-accent/20 rounded-full blur-[120px] pointer-events-none"></div>

      {/* Sidebar Queue View */}
      <div className="w-80 glass-panel border-r border-white/5 flex flex-col z-10">
        <div className="p-6 border-b border-white/5">
          <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
            IntelliDoc HITL
          </h1>
          <p className="text-xs text-slate-400 mt-1">Review Queue ({queue.length})</p>
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {queue.length === 0 ? (
            <div className="text-center text-slate-500 mt-10">Queue Empty! 🎉</div>
          ) : (
            queue.map(doc => (
              <div 
                key={doc.id}
                onClick={() => setActiveDoc(doc)}
                className={`p-4 rounded-xl cursor-pointer transition-all duration-300 ${
                  activeDoc?.id === doc.id 
                    ? 'bg-primary/20 border-primary/50 border' 
                    : 'bg-white/5 border-white/5 border hover:bg-white/10'
                }`}
              >
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold px-2 py-1 rounded bg-slate-800/80 text-blue-300">
                    {doc.document_type}
                  </span>
                  <span className={`text-xs font-bold ${doc.overall_score < 0.7 ? 'text-danger' : 'text-amber-400'}`}>
                    {(doc.overall_score * 100).toFixed(0)}% Conf
                  </span>
                </div>
                <p className="text-sm font-medium text-slate-300 truncate">{doc.id}</p>
                <p className="text-xs text-slate-500 mt-1">{new Date(doc.timestamp).toLocaleTimeString()}</p>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main Workspace */}
      <div className="flex-1 flex flex-col h-screen z-10 relative">
        {activeDoc ? (
          <div className="flex-1 flex p-6 gap-6 h-full">
            
            {/* PDF Viewer Mock */}
            <div className="flex-[3] glass-panel rounded-2xl flex flex-col overflow-hidden relative group">
              <div className="bg-slate-900/80 p-3 border-b border-white/5 flex justify-between items-center">
                <span className="text-sm font-code text-slate-400">{activeDoc.gcs_uri.split('/').pop()}</span>
                <span className="text-xs bg-slate-800 px-2 py-1 rounded">Page 1 of 1</span>
              </div>
              
              <div className="flex-1 bg-slate-100 flex items-center justify-center p-8 overflow-hidden relative">
                 {/* Placeholder for PDF Iframe */}
                 <div className="w-full h-full max-w-2xl bg-white shadow-xl flex flex-col text-slate-800 p-10 font-serif overflow-hidden">
                    {activeDoc.document_type === "INVOICE" ? (
                      <>
                        <div className="flex justify-between border-b pb-4 mb-8">
                          <h1 className="text-3xl font-bold text-slate-800">INVOICE</h1>
                          <div className="text-right">
                            <p className="font-bold text-lg">Acme Corp</p>
                            <p className="text-sm text-slate-500">Invoice #: 9942</p>
                            <p className="text-sm text-slate-500">Date: 2026-03-10</p>
                          </div>
                        </div>
                        <div className="flex-1">
                          <p className="mb-4">Bill To: Client LLC</p>
                          <table className="w-full text-left mb-8">
                            <tr className="border-b"><th className="py-2">Item</th><th>Amount</th></tr>
                            <tr className="border-b"><td className="py-2">Consulting Config</td><td>$4,520.00</td></tr>
                          </table>
                          <div className="text-right font-bold text-xl mt-auto">
                            Total: <span className="text-primary hover:bg-yellow-200 cursor-pointer transition-colors duration-300">$4,520.00</span>
                          </div>
                        </div>
                      </>
                    ) : (
                      <>
                        <h1 className="text-2xl font-bold mb-6 text-center underline">VENDOR CONTRACT AGREEMENT</h1>
                        <p className="mb-4 text-sm leading-relaxed text-justify">
                          This Vendor Agreement ("Agreement") is dated _________ (Effective Date), 
                          by and between [Vendor Name] and Client LLC. The vendor agrees to...
                        </p>
                        <p className="mt-auto pt-10 border-t">
                          Vendor Signature: ____________________ <br/><span className="text-red-500/50 text-xs font-bold">(MISSING SIGNATURE)</span>
                        </p>
                      </>
                    )}
                    {/* Simulated Highlighting Overlay */}
                    <div className="absolute top-0 left-0 w-full h-full pointer-events-none bg-blue-500/5 opacity-0 group-hover:opacity-100 transition-opacity duration-700"></div>
                 </div>
              </div>
            </div>

            {/* Editing Pane */}
            <div className="flex-[2] glass-panel rounded-2xl flex flex-col overflow-hidden">
              <div className="p-5 border-b border-white/5 bg-slate-900/40">
                 <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full animate-pulse bg-amber-400"></span>
                    Human Verification Required
                 </h2>
                 <p className="text-xs text-slate-400 mt-1">
                    AI confidence fell below 80% threshold. Please correct highlighted fields.
                 </p>
              </div>

              <div className="flex-1 p-5 overflow-y-auto space-y-5">
                {Object.keys(editedFields).map((key) => {
                  const conf = activeDoc.confidence_scores[key] || 0;
                  const isLowConf = conf < 0.8;
                  
                  return (
                    <div key={key} className="flex flex-col gap-2 relative group">
                      <label className="text-xs font-semibold text-slate-300 flex justify-between">
                        {key}
                        <span className={`px-2 py-0.5 rounded text-[10px] ${isLowConf ? 'bg-danger/20 text-danger border border-danger/30' : 'text-emerald-400'}`}>
                          {isLowConf ? 'Needs Check' : 'Trusted'} ({(conf * 100).toFixed(0)}%)
                        </span>
                      </label>
                      <input 
                        type="text" 
                        value={editedFields[key] || ''}
                        onChange={(e) => handleFieldChange(key, e.target.value)}
                        className={`glass-input w-full ${isLowConf ? 'border-amber-500/50 shadow-[0_0_15px_rgba(245,158,11,0.1)] focus:ring-amber-500/50' : 'border-white/5 focus:ring-primary/50'}`}
                      />
                    </div>
                  );
                })}
              </div>

              <div className="p-5 border-t border-white/5 bg-slate-900/40 flex gap-3">
                <button 
                  onClick={handleReject}
                  className="flex-1 py-3 px-4 rounded-xl font-semibold text-sm bg-white/5 hover:bg-danger/20 hover:text-danger text-slate-300 transition-colors duration-300"
                >
                  Reject & Escalate
                </button>
                <button 
                  onClick={handleApprove}
                  className="flex-1 py-3 px-4 rounded-xl font-semibold text-sm bg-primary/90 hover:bg-primary text-white shadow-[0_0_20px_rgba(59,130,246,0.5)] transition-all duration-300 hover:scale-[1.02]"
                >
                  Approve & Process
                </button>
              </div>
            </div>

          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
             <div className="text-center">
                <h2 className="text-2xl font-bold text-slate-300 mb-2">You're All Caught Up</h2>
                <p className="text-slate-500">The AI is crushing it. No documents require manual review.</p>
             </div>
          </div>
        )}
      </div>
    </div>
  );
}
