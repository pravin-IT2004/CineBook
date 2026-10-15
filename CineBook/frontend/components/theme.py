"""Cinema-inspired dark theme (CSS injected once per run)."""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700;800&display=swap');
:root{
  --cb-red:#E50914; --cb-red-dark:#9F0610; --cb-bg:#0B0B10; --cb-panel:#14141C; --cb-panel-2:#1B1B25;
  --cb-line:#2A2A37; --cb-text:#F4F4F6; --cb-muted:#A0A0B4; --cb-gold:#F5C542; --cb-teal:#2DD4BF;
  --cb-violet:#A78BFA; --cb-green:#22C55E; --cb-amber:#F59E0B; --cb-blue:#3B82F6;
}
html, body, .stApp, .stMarkdown, button, input, textarea, select { font-family:'Inter', system-ui, sans-serif; }
.stApp{
  background:
    radial-gradient(900px 480px at 0% -10%, rgba(229,9,20,.16), transparent 60%),
    radial-gradient(700px 400px at 100% 0%, rgba(120,40,200,.08), transparent 60%),
    var(--cb-bg);
}
h1, h2, h3, .cb-display{ font-family:'Bebas Neue',Impact,'Arial Narrow Bold','Oswald',sans-serif !important; letter-spacing:.6px; font-weight:400 !important; }
h1{ font-size:2.6rem !important; } h2{ font-size:2rem !important; } h3{ font-size:1.55rem !important; }
.block-container{ padding-top:1.6rem; padding-bottom:3rem; max-width:1280px; }
[data-testid="stSidebar"]{ background:linear-gradient(180deg,#101018 0%,#0B0B10 100%); border-right:1px solid var(--cb-line); }
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]{ border-radius:10px; }
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover{ background:rgba(229,9,20,.12); }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"]{
  background:linear-gradient(135deg,#E50914,#B20710); border:0; font-weight:700; box-shadow:0 6px 18px rgba(229,9,20,.25);
}
.stButton > button[kind="primary"]:hover{ filter:brightness(1.1); }
div[data-testid="stExpander"] details, div[data-testid="stForm"]{ border-color:var(--cb-line) !important; background:rgba(20,20,28,.6); border-radius:14px; }
div[data-testid="stMetric"]{ background:var(--cb-panel); border:1px solid var(--cb-line); padding:14px 16px; border-radius:14px; }
.stTabs [data-baseweb="tab-list"]{ gap:6px; }
.stTabs [data-baseweb="tab"]{ background:var(--cb-panel); border-radius:10px 10px 0 0; padding:8px 16px; }

/* ---------- brand & layout pieces ---------- */
.cb-brand{ display:flex; align-items:center; gap:10px; margin:4px 0 14px; }
.cb-brand .logo{ width:38px; height:38px; border-radius:10px; background:linear-gradient(135deg,#E50914,#7A040B);
  display:grid; place-items:center; font-size:20px; box-shadow:0 6px 16px rgba(229,9,20,.35); }
.cb-brand .name{ font-family:'Bebas Neue',sans-serif; font-size:30px; letter-spacing:1.5px; line-height:1; }
.cb-brand .name span{ color:var(--cb-red); }
.cb-brand .tag{ font-size:11px; color:var(--cb-muted); letter-spacing:.3px; }
.cb-userbox{ background:var(--cb-panel); border:1px solid var(--cb-line); border-radius:12px; padding:10px 12px; margin:6px 0 10px; font-size:13px; }
.cb-userbox b{ display:block; font-size:14px; }
.cb-navlabel{ font-size:11px; text-transform:uppercase; letter-spacing:1.4px; color:var(--cb-muted); margin:14px 0 4px 4px; }

.cb-page-head{ margin:0 0 18px; }
.cb-page-head .eyebrow{ color:var(--cb-red); font-weight:700; font-size:12px; letter-spacing:2px; text-transform:uppercase; }
.cb-page-head h1{ margin:2px 0 4px !important; padding:0 !important; }
.cb-page-head p{ color:var(--cb-muted); margin:0; }

.cb-hero{ position:relative; overflow:hidden; border-radius:22px; padding:38px 36px; margin-bottom:26px;
  background:linear-gradient(110deg, rgba(11,11,16,.96) 30%, rgba(11,11,16,.55)), var(--hero-bg, #200);
  border:1px solid var(--cb-line); background-size:cover; background-position:center; }
.cb-hero h1{ font-size:3.4rem !important; line-height:1; margin:0 0 10px !important; }
.cb-hero h1 em{ color:var(--cb-red); font-style:normal; }
.cb-hero p{ color:#D6D6E0; max-width:560px; font-size:1.05rem; }
.cb-hero .strip{ position:absolute; right:-40px; top:0; bottom:0; width:42%; display:flex; gap:12px; transform:rotate(8deg) translateY(-30px); opacity:.85; }
.cb-hero .strip .p{ flex:1; border-radius:14px; background-size:cover; box-shadow:0 20px 40px rgba(0,0,0,.6); }

/* ---------- movie cards ---------- */
.cb-card{ background:var(--cb-panel); border:1px solid var(--cb-line); border-radius:16px; overflow:hidden;
  transition:transform .15s ease, border-color .15s ease; height:100%; }
.cb-card:hover{ transform:translateY(-3px); border-color:#3a3a4a; }
.cb-poster{ position:relative; aspect-ratio:2/3; background-size:cover; background-position:center; }
.cb-poster .chip{ position:absolute; top:10px; left:10px; }
.cb-poster .rating{ position:absolute; top:10px; right:10px; background:rgba(0,0,0,.72); padding:4px 8px; border-radius:8px; font-weight:700; font-size:13px; }
.cb-card .body{ padding:12px 14px 14px; }
.cb-card .title{ font-weight:700; font-size:15.5px; line-height:1.25; margin-bottom:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cb-card .meta{ color:var(--cb-muted); font-size:12.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

.cb-badge{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:11.5px; font-weight:700; letter-spacing:.3px; border:1px solid transparent; margin:0 4px 4px 0; }
.cb-badge.red{ background:rgba(229,9,20,.16); color:#FF5C66; border-color:rgba(229,9,20,.35); }
.cb-badge.green{ background:rgba(34,197,94,.14); color:#4ADE80; border-color:rgba(34,197,94,.35); }
.cb-badge.amber{ background:rgba(245,158,11,.14); color:#FBBF24; border-color:rgba(245,158,11,.35); }
.cb-badge.blue{ background:rgba(59,130,246,.14); color:#93C5FD; border-color:rgba(59,130,246,.35); }
.cb-badge.grey{ background:rgba(160,160,180,.12); color:#C8C8D4; border-color:rgba(160,160,180,.25); }
.cb-badge.solid{ background:var(--cb-red); color:#fff; }

.cb-panel{ background:var(--cb-panel); border:1px solid var(--cb-line); border-radius:16px; padding:18px 20px; }
.cb-muted{ color:var(--cb-muted); }
.cb-kv{ display:grid; grid-template-columns:110px 1fr; gap:6px 12px; font-size:14px; }
.cb-kv .k{ color:var(--cb-muted); text-transform:uppercase; font-size:11px; letter-spacing:1px; padding-top:3px; }

.cb-empty{ text-align:center; padding:46px 20px; border:1px dashed var(--cb-line); border-radius:18px; background:rgba(20,20,28,.5); margin:10px 0 18px; }
.cb-empty .icon{ font-size:44px; margin-bottom:6px; }
.cb-empty h3{ margin:4px 0 !important; }
.cb-empty p{ color:var(--cb-muted); margin:0 auto; max-width:440px; }

.cb-stat{ background:linear-gradient(160deg,var(--cb-panel-2),var(--cb-panel)); border:1px solid var(--cb-line); border-radius:16px; padding:16px 18px; height:100%; }
.cb-stat .label{ color:var(--cb-muted); font-size:12px; text-transform:uppercase; letter-spacing:1.2px; }
.cb-stat .value{ font-family:'Bebas Neue',sans-serif; font-size:34px; line-height:1.1; margin-top:4px; }
.cb-stat .sub{ color:var(--cb-muted); font-size:12px; }

/* ---------- offers ---------- */
.cb-offer{ position:relative; border-radius:16px; padding:18px 20px; background:linear-gradient(135deg,#1E1018,#14141C);
  border:1px dashed rgba(229,9,20,.55); height:100%; }
.cb-offer .code{ font-family:'Bebas Neue',sans-serif; font-size:30px; letter-spacing:2px; color:#fff; }
.cb-offer .label{ color:var(--cb-gold); font-weight:700; }
.cb-offer .desc{ color:var(--cb-muted); font-size:13px; margin-top:6px; }

/* ---------- showtimes ---------- */
.cb-cinema{ background:var(--cb-panel); border:1px solid var(--cb-line); border-radius:16px; padding:14px 18px 6px; margin-bottom:12px; }
.cb-cinema .name{ font-weight:700; font-size:16px; }
.cb-cinema .addr{ color:var(--cb-muted); font-size:12.5px; margin-bottom:8px; }

/* ---------- seat map ---------- */
.cb-screen{ margin:6px auto 22px; width:78%; text-align:center; }
.cb-screen .curve{ height:10px; border-radius:50% 50% 0 0 / 100% 100% 0 0; border-top:4px solid #E9E9F1;
  box-shadow:0 -10px 30px rgba(233,233,241,.35); }
.cb-screen .lbl{ color:var(--cb-muted); font-size:11px; letter-spacing:4px; margin-top:6px; }
.cb-catlabel{ text-align:center; color:var(--cb-muted); font-size:11px; letter-spacing:2px; text-transform:uppercase; margin:12px 0 4px; }
.st-key-seatgrid{ overflow-x:auto; padding-bottom:6px; }
.st-key-seatgrid [data-testid="stHorizontalBlock"], .st-key-seatgrid div[class*="st-key-row_"]{ min-width:max-content; }
.st-key-seatgrid button{ min-height:30px !important; height:30px; width:32px; min-width:32px; padding:0 !important;
  font-size:11px !important; font-weight:700; border-radius:8px 8px 4px 4px !important; }
.st-key-seatgrid button p{ font-size:11px !important; }
.cb-rowlabel{ width:22px; height:30px; text-align:center; color:var(--cb-muted); font-weight:700; font-size:12px; line-height:30px; }
.st-key-seatgrid [data-testid="stMarkdownContainer"]{ margin:0; }
.st-key-seatgrid div[class*="st-key-row_"] .stMarkdown{ margin:0 !important; height:30px; }
.cb-aisle{ width:16px; }
.cb-legend{ display:flex; flex-wrap:wrap; gap:14px; justify-content:center; font-size:12.5px; color:var(--cb-muted); margin:16px 0 4px; }
.cb-legend span{ display:inline-flex; align-items:center; gap:6px; }
.cb-legend i{ width:16px; height:16px; border-radius:5px 5px 3px 3px; display:inline-block; }

/* ---------- ticket ---------- */
.cb-ticket{ display:flex; flex-wrap:wrap; background:#F7F7FA; color:#111118; border-radius:20px; overflow:hidden; box-shadow:0 20px 50px rgba(0,0,0,.5); }
.cb-ticket .main{ flex:1 1 380px; padding:22px 24px; position:relative; }
.cb-ticket .stub{ flex:0 0 230px; padding:22px; background:#111118; color:#fff; text-align:center; border-left:2px dashed #555;
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; }
.cb-ticket .brand{ font-family:'Bebas Neue',sans-serif; font-size:26px; letter-spacing:2px; color:#E50914; }
.cb-ticket .movie{ font-family:'Bebas Neue',sans-serif; font-size:34px; line-height:1; margin:6px 0 2px; color:#111118; }
.cb-ticket .meta{ color:#5B5B6B; font-size:13px; margin-bottom:12px; }
.cb-ticket .grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px 18px; }
.cb-ticket .grid .k{ font-size:10.5px; letter-spacing:1.2px; text-transform:uppercase; color:#7A7A8A; }
.cb-ticket .grid .v{ font-weight:700; font-size:15px; }
.cb-ticket .thumb{ float:right; width:74px; aspect-ratio:2/3; border-radius:10px; background-size:cover; margin-left:12px; }
.cb-ticket .stub img{ width:170px; height:170px; border-radius:10px; background:#fff; padding:6px; }
.cb-ticket .ref{ font-family:'Bebas Neue',sans-serif; font-size:21px; letter-spacing:1.5px; white-space:nowrap; }
.cb-ticket.cancelled{ filter:grayscale(.85); opacity:.85; }
.cb-pricebox{ margin-top:14px; border-top:1px solid #DDDDE5; padding-top:10px; font-size:13.5px; }
.cb-pricebox .row{ display:flex; justify-content:space-between; padding:2px 0; }
.cb-pricebox .total{ font-weight:800; font-size:16px; }
.cb-pricebox .disc{ color:#15803D; }

.cb-booking{ background:var(--cb-panel); border:1px solid var(--cb-line); border-radius:16px; padding:14px 16px; margin-bottom:6px; display:flex; gap:14px; align-items:center; }
.cb-booking .thumb{ width:54px; min-width:54px; aspect-ratio:2/3; border-radius:8px; background-size:cover; }
.cb-booking .t{ font-weight:700; font-size:16px; }
.cb-booking .m{ color:var(--cb-muted); font-size:13px; }

@media (max-width: 640px){
  .cb-hero{ padding:26px 20px; } .cb-hero h1{ font-size:2.4rem !important; } .cb-hero .strip{ display:none; }
  .cb-ticket .stub{ flex:1 1 100%; border-left:0; border-top:2px dashed #555; }
  h1{ font-size:2.1rem !important; }
}
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
