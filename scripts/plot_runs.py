"""Plot how training runs improve: win rate and clean-win rate against decisions trained.

  python scripts/plot_runs.py runs/pilot_check runs/pilot_check2 --baseline-win 0.61 --baseline-clean 0.37

Each run is a --run-dir of scripts/train_ppo.py; its metrics.jsonl has one line per update.
The line is the mean of the last 3 updates and the dots are each update's own value, which is
noisy: an update sees about 100 episodes spread over every battle. --state limits the plot to
one battle. --return adds a return panel, but returns compare only between runs with the same
reward. The random-play baselines are reference lines when given. Writes --out (a PNG).
"""
import argparse, json, os, sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The dataviz reference palette, light mode: categorical slots in their fixed order, and chrome.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
WINDOW = 3


def load(run_dir: str, state: str | None) -> list[dict]:
    """One {decisions, win_rate, clean_win_rate, mean_return} per update, for the whole run or one battle."""
    rows = []
    with open(os.path.join(run_dir, "metrics.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            s = r if state is None else r["states"].get(state if state.endswith(".state") else state + ".state")
            if s and s.get("episodes"):
                rows.append({"decisions": r["decisions"], "win_rate": s.get("win_rate"),
                             "clean_win_rate": s.get("clean_win_rate"), "mean_return": s.get("mean_return")})
    return rows


def rolling(values: list[float]) -> list[float]:
    return [sum(values[max(0, i - WINDOW + 1):i + 1]) / len(values[max(0, i - WINDOW + 1):i + 1])
            for i in range(len(values))]


def label_ends(ax, ends: list[tuple[float, float, str]], fmt):
    """Label each line's last point in a column right of the plot, run name and value in ink, with
    a thin leader line back to the point. Labels are spread apart only where lines end close
    together, so each stays readable and still points at its own line."""
    lo, hi = ax.get_ylim()
    gap = 0.07 * (hi - lo)
    placed = []
    for x, y, name in sorted(ends, key=lambda e: e[1]):
        placed.append((x, y, name, max(y, placed[-1][3] + gap) if placed else y))
    for x, y, name, y_label in placed:
        ax.annotate(f"{name}  {fmt(y)}", (x, y), xytext=(1.02, y_label), textcoords=("axes fraction", "data"),
                    va="center", color=INK_2, fontsize=9, annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=AXIS, linewidth=0.8, shrinkA=0, shrinkB=3))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run directories, each with a metrics.jsonl")
    ap.add_argument("--state", help="one battle's numbers, such as weak_lead_vs_lileep")
    ap.add_argument("--baseline-win", type=float, help="random play's win rate, drawn as a reference line")
    ap.add_argument("--baseline-clean", type=float, help="random play's clean-win rate")
    ap.add_argument("--baseline-return", type=float, help="random play's return, with --return")
    ap.add_argument("--return", dest="with_return", action="store_true", help="add a return panel")
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "progress.png"))
    args = ap.parse_args()
    if len(args.runs) > len(SERIES):
        sys.exit(f"at most {len(SERIES)} runs per chart")

    panels = [("win_rate", "Win rate", args.baseline_win), ("clean_win_rate", "Clean-win rate (won with no faint)", args.baseline_clean)]
    if args.with_return:
        panels.append(("mean_return", "Return (compare only runs with the same reward)", args.baseline_return))
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 10, "text.color": INK, "axes.labelcolor": INK_2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": AXIS})
    fig, axes = plt.subplots(1, len(panels), figsize=(6.4 * len(panels), 4.0), facecolor=SURFACE, squeeze=False)
    runs = [(os.path.basename(os.path.normpath(r)), load(r, args.state)) for r in args.runs]

    for ax, (key, title, baseline) in zip(axes[0], panels):
        ax.set_facecolor(SURFACE)
        ax.set_title(title, loc="left", color=INK, fontsize=11, pad=10)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.set_xlabel("Decisions trained")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x / 1000:g}k" if x else "0"))
        if key != "mean_return":
            ax.set_ylim(0, 1)
        fmt = (lambda v: f"{v:.2f}") if key != "mean_return" else (lambda v: f"{v:+.1f}")
        ends = []
        for color, (name, rows) in zip(SERIES, runs):
            pts = [(r["decisions"], r[key]) for r in rows if r[key] is not None]
            if not pts:
                continue        # this run predates the metric (clean wins came with faint counting)
            xs, ys = zip(*pts)
            ax.plot(xs, ys, "o", color=color, markersize=4, alpha=0.35, markeredgewidth=0)
            mean = rolling(list(ys))
            ax.plot(xs, mean, color=color, linewidth=2, solid_capstyle="round", solid_joinstyle="round", label=name)
            ends.append((xs[-1], mean[-1], name))
        if baseline is not None:
            ax.axhline(baseline, color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)))
            # At the right end, under the line: the runs start beside random play and end above it.
            ax.annotate(f"random play {baseline:.2f}" if key != "mean_return" else f"random play {baseline:+.1f}",
                        (1, baseline), xycoords=("axes fraction", "data"), xytext=(-4, -4), textcoords="offset points",
                        ha="right", va="top", color=INK_2, fontsize=9)
        label_ends(ax, ends, fmt)
    if len(runs) > 1:
        fig.legend(*axes[0][0].get_legend_handles_labels(), loc="upper right", ncol=len(runs), frameon=False,
                   labelcolor=INK)
    fig.suptitle("Training progress" + (f": {args.state}" if args.state else ""), x=0.01, ha="left", color=INK,
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.subplots_adjust(wspace=0.45)       # room for the end labels between panels
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, dpi=130, facecolor=SURFACE, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
