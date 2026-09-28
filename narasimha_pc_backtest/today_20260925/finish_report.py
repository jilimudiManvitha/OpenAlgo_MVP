"""Adapt the copied historical dashboard labels/axes for a one-session basket."""

from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    path = HERE / "output/index.html"
    html = path.read_text(encoding="utf-8")
    html = html.replace("All 50 stocks", "All selected instruments")
    html = html.replace(
        "${R.audits.length}/50 symbols",
        "${R.audits.length}/${R.config.symbols.length} selected instruments",
    )
    html = html.replace("Observed ${first} → ${last}.", "Warmup/source dates ${first} → ${last}.")
    html = html.replace(
        "September 25 is a partial source day; JIOFIN starts in August 2023.",
        "Replay uses completed candles through each instrument’s square-off. This one-day daily-close drawdown does not measure intraday drawdown.",
    )
    html = html.replace(
        "xaxis:{gridcolor:'#223047'}", "xaxis:{gridcolor:'#223047',type:'category'}"
    )
    html = html.replace(
        "mode:'lines',line:{color:'#55d4bd'}", "mode:'lines+markers',line:{color:'#55d4bd'}"
    )
    html = html.replace(
        "mode:'lines',line:{color:'#fb8a99'}", "mode:'lines+markers',line:{color:'#fb8a99'}"
    )
    html = html.replace(
        "rangeslider:{visible:false},title:'IST'",
        "type:'date',rangeslider:{visible:false},title:'IST'",
    )
    html = html.replace("http://127.0.0.1:8782", "http://127.0.0.1:8783")
    path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
