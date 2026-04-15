import { useState } from "react";

function App() {
  const [ad, setAd] = useState("");
  const [url, setUrl] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    // ✅ Validation
    if (!ad || !url) {
      setError("Please enter both Ad Content and URL");
      return;
    }

    setLoading(true);
    setData(null);
    setError("");

    const formData = new FormData();
    formData.append("target_url", url);
    formData.append("ad_link", ad);

    try {
      const res = await fetch("http://localhost:8000/api/personalize", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error("Backend error");
      }

      const result = await res.json();

      if (!result.success) {
        throw new Error("Processing failed");
      }

      setData(result.data);

    } catch (err) {
      setError("Failed to process request. Check backend.");
    }

    setLoading(false);
  };

  return (
    <div className="container">
      <h1>AI Landing Page Personalizer</h1>

      {/* INPUT */}
      <div className="card">
        <h2>Input</h2>

        <label>Ad Content</label>
        <textarea
          value={ad}
          onChange={(e) => setAd(e.target.value)}
          placeholder="e.g. 50% OFF for students - limited time"
        />

        <label>Landing Page URL</label>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
        />

        <button onClick={handleSubmit} disabled={loading}>
          {loading ? "Processing..." : "Generate"}
        </button>

        {/* ERROR */}
        {error && (
          <p style={{ color: "red", marginTop: "10px" }}>{error}</p>
        )}
      </div>

      {/* EMPTY STATE */}
      {!data && !loading && (
        <div className="card">
          <p>Enter details and click Generate to see results.</p>
        </div>
      )}

      {/* LOADING */}
      {loading && (
        <div className="card">
          <p>⏳ AI is analyzing and optimizing the page...</p>
        </div>
      )}

      {/* OUTPUT */}
      {data && (
        <>
          {/* HOW IT WORKS */}
          <div className="card">
            <h2>⚙️ How It Works</h2>
            <ol>
              <li>Analyze Ad (Offer, Audience, Tone)</li>
              <li>Extract Landing Page Content</li>
              <li>Detect Mismatches</li>
              <li>Generate CRO Improvements</li>
              <li>Render Personalized Page</li>
            </ol>
          </div>

          {/* AD ANALYSIS */}
          <div className="card">
            <h2>Ad Analysis</h2>
            <p><b>Offer:</b> <span style={{color:"#22c55e"}}>{data.ad_analysis?.offer}</span></p>
            <p><b>Audience:</b> {data.ad_analysis?.audience}</p>
            <p><b>Tone:</b> {data.ad_analysis?.tone}</p>
          </div>

          {/* MISMATCH */}
          <div className="card">
            <h2>Mismatches</h2>
            <ul>
              {data.mismatches?.length > 0 ? (
                data.mismatches.map((m, i) => <li key={i}>{m}</li>)
              ) : (
                <li>No major mismatches detected</li>
              )}
            </ul>
          </div>

          {/* IMPROVEMENTS */}
          <div className="card">
            <h2>Improvements</h2>
            <h2 style={{color:"#22c55e"}}>{data.cta}</h2>
            <p><b>Paragraph:</b> {data.paragraph}</p>
          </div>

          {/* BEFORE AFTER */}
          <div className="card">
            <h2>Before vs After</h2>
            {data.replacements?.length > 0 ? (
              data.replacements.map((item, i) => (
                <div key={i}>
                  <p><b>Old:</b> {item.original}</p>
                  <p><b>New:</b> {item.new}</p>
                  <hr />
                </div>
              ))
            ) : (
              <p>No changes required</p>
            )}
          </div>

          {/* REASON */}
          <div className="card">
            <h2>Why Changes?</h2>
            <p>{data.reason}</p>
          </div>

          {/* PREVIEW */}
          <div className="card">
            <h2 style={{ color: "#22c55e" }}>
              🚀 Enhanced Landing Page (CRO Optimized)
            </h2>

            <p style={{ fontSize: "14px", color: "#94a3b8" }}>
              This is the original page enhanced based on ad intent using AI-driven CRO principles.
            </p>

            <iframe
              srcDoc={data.html}
              width="100%"
              height="500"
              style={{ border: "none", background: "white" }}
            />
          </div>
        </>
      )}
    </div>
  );
}

export default App;