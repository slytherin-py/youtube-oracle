import { useState } from "react";
import axios from "axios";
import {
  BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine
} from "recharts";
import { Loader2, Play, Info, AlertCircle, TrendingUp } from "lucide-react";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

type Contribution = { feature: string; value: number; shap: number };
type ScoreResponse = {
  video_id: string;
  title: string;
  channel: string;
  category: string;
  probability: number;
  verdict: string;
  base_rate: number;
  top_contributions: Contribution[];
  metadata: {
    current_views: number;
    current_likes: number;
    published_at: string;
    model_auc_on_holdout: number;
    note: string;
  };
};

const formatNumber = (n: number) => {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toString();
};

const verdictColor = (p: number) => {
  if (p >= 0.75) return "text-emerald-400";
  if (p >= 0.55) return "text-lime-400";
  if (p >= 0.35) return "text-amber-400";
  return "text-rose-400";
};

export default function App() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [showAbout, setShowAbout] = useState(false);

  const handlePredict = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await axios.post(`${API}/score`, { video: url });
      setResult(res.data);
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const chartData = result?.top_contributions.map(c => ({
    name: c.feature,
    shap: c.shap,
  })) ?? [];

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="border-b border-neutral-800">
        <div className="max-w-5xl mx-auto px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-6 h-6 text-emerald-400" />
            <h1 className="text-xl font-semibold tracking-tight">Play Oracle</h1>
          </div>
          <button
            onClick={() => setShowAbout(!showAbout)}
            className="text-sm text-neutral-400 hover:text-neutral-100 flex items-center gap-1.5"
          >
            <Info className="w-4 h-4" />
            {showAbout ? "Hide" : "About"}
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-12">
        {showAbout && <AboutPanel />}

        <div className="text-center mb-10">
          <h2 className="text-4xl font-bold tracking-tight mb-3">
            Will this video go viral?
          </h2>
          <p className="text-neutral-400 max-w-xl mx-auto">
            Paste any Play URL. An XGBoost model predicts virality probability and shows you exactly which features influenced the call.
          </p>
        </div>

        <div className="flex gap-3 mb-12 max-w-2xl mx-auto">
          <div className="relative flex-1">
            <Play className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-neutral-500" />
            <input
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handlePredict()}
              placeholder="https://www.Play.com/watch?v=..."
              className="w-full bg-neutral-900 border border-neutral-800 rounded-lg pl-10 pr-4 py-3 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>
          <button
            onClick={handlePredict}
            disabled={loading || !url.trim()}
            className="bg-emerald-500 hover:bg-emerald-400 disabled:bg-neutral-700 disabled:text-neutral-500 text-black font-medium px-6 py-3 rounded-lg transition-colors flex items-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Predict
          </button>
        </div>

        {error && (
          <div className="max-w-2xl mx-auto mb-8 bg-rose-950/40 border border-rose-900 rounded-lg px-4 py-3 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-medium text-rose-300">Error</div>
              <div className="text-sm text-rose-400/80">{error}</div>
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-6">
            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6">
              <div className="text-sm text-neutral-500 mb-1">{result.channel}</div>
              <h3 className="text-lg font-semibold mb-4 line-clamp-2">{result.title}</h3>

              <div className="grid grid-cols-3 gap-6 pt-4 border-t border-neutral-800">
                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Probability</div>
                  <div className={`text-4xl font-bold ${verdictColor(result.probability)}`}>
                    {(result.probability * 100).toFixed(1)}%
                  </div>
                  <div className={`text-sm mt-1 ${verdictColor(result.probability)}`}>{result.verdict}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Current views</div>
                  <div className="text-2xl font-semibold">{formatNumber(result.metadata.current_views)}</div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1">Current likes</div>
                  <div className="text-2xl font-semibold">{formatNumber(result.metadata.current_likes)}</div>
                </div>
              </div>
            </div>

            <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6">
              <h4 className="text-sm uppercase tracking-wider text-neutral-400 mb-1">
                Why the model predicted this
              </h4>
              <p className="text-xs text-neutral-500 mb-6">
                SHAP values. Green bars pushed the prediction toward viral, red pushed away. Base rate was {(result.base_rate * 100).toFixed(1)}%.
              </p>
              <div className="w-full h-80">
                <ResponsiveContainer>
                  <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 40 }}>
                    <XAxis type="number" stroke="#525252" />
                    <YAxis dataKey="name" type="category" stroke="#a3a3a3" width={140} />
                    <ReferenceLine x={0} stroke="#525252" />
                    <Tooltip
                      contentStyle={{ background: "#171717", border: "1px solid #404040", borderRadius: 8 }}
                      formatter={(v) => (typeof v === "number" ? v.toFixed(3) : String(v))}
                    />
                    <Bar dataKey="shap">
                      {chartData.map((d, i) => (
                        <Cell key={i} fill={d.shap > 0 ? "#10b981" : "#f43f5e"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="bg-neutral-900/40 border border-neutral-800 rounded-xl p-4 text-sm text-neutral-400">
              <span className="text-neutral-500">Model note — </span>
              {result.metadata.note}
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-neutral-800 mt-20">
        <div className="max-w-5xl mx-auto px-6 py-6 text-xs text-neutral-500 flex justify-between">
          <span>Play Oracle · v0.1 · Trained on Kaggle 2017-18</span>
          <a href="https://github.com/slytherin-py/Play-oracle" className="hover:text-neutral-300" target="_blank" rel="noreferrer">
            GitHub →
          </a>
        </div>
      </footer>
    </div>
  );
}

function AboutPanel() {
  return (
    <div className="mb-12 bg-neutral-900 border border-neutral-800 rounded-xl p-6 space-y-4 text-sm text-neutral-300">
      <h3 className="text-lg font-semibold text-neutral-100">About this model</h3>
      <div>
        <div className="font-medium text-neutral-200 mb-1">What it does</div>
        <p className="text-neutral-400">
          Predicts whether a Play video will cross a virality threshold, given only features available before the fact: title, channel size, category, publish timing, and early engagement ratios.
        </p>
      </div>
      <div>
        <div className="font-medium text-neutral-200 mb-1">How it was trained</div>
        <p className="text-neutral-400">
          XGBoost classifier trained on 6,351 US videos from the Kaggle Trending Play dataset (2017-18). 80/20 time-based split to prevent leakage — train on older, test on newer. Holdout AUC 0.954, PR-AUC 0.975.
        </p>
      </div>
      <div>
        <div className="font-medium text-neutral-200 mb-1">Known limitations</div>
        <ul className="text-neutral-400 list-disc list-inside space-y-1">
          <li>Training data is from 2017-18. Play's algorithm and audience have changed since.</li>
          <li>Play hid public dislike counts in 2021, so that feature is always zero now. The model was trained with it, so it adjusts in a way that's slightly miscalibrated for recent videos.</li>
          <li>Current "views" at scoring time leaks future information for old videos. v1 will retrain on live-captured early-hour snapshots to fix this.</li>
        </ul>
      </div>
      <div>
        <div className="font-medium text-neutral-200 mb-1">What's next</div>
        <p className="text-neutral-400">
          A live data pipeline is collecting hourly trending videos. Once enough labeled snapshots accumulate, the model retrains on early-lifecycle features only — at which point accuracy will drop to a more honest 0.78-0.85 AUC range, and predictions will be calibrated on today's Play rather than 2018's.
        </p>
      </div>
    </div>
  );
}

