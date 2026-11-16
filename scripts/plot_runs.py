"""Plot how training runs improve: win rate and clean-win rate against decisions trained.

  python scripts/plot_runs.py runs/pilot_check runs/pilot_check2 --baseline-win 0.61 --baseline-clean 0.37
  python scripts/plot_runs.py runs/pilot --by-battle [--metric win]

Each run is a --run-dir of scripts/train_ppo.py; its metrics.jsonl has one line per update.
The line is the mean of the last 3 updates and the dots are each update's own value, which is
noisy: an update sees about 100 episodes spread over every battle. --state limits the plot to
one battle. --return adds a return panel, but returns compare only between runs with the same
reward. The random-play baselines are reference lines when given.

--by-battle draws a heatmap per run instead: a row per battle, a column per --bin updates, and
the clean-win rate (or --metric win) of the episodes in that stretch, darker for higher. Each
row ends with its first and last values. Writes --out (a PNG).
"""
import argparse, json, os, sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The dataviz reference palette, light mode: categorical slots in their fixed order, and chrome.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
# The reference sequential blue, steps 100 to 700, light (low) to dark (high); EMPTY is a cell with no episodes.
RAMP = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf",
        "#1c5cab", "#184f95", "#104281", "#0d366b")
EMPTY = "#f0efec"
WINDOW = 3
METRICS = {"clean": ("clean_win_rate", "Clean-win rate (won with no faint)"), "win": ("win_rate", "Win rate")}


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


def battle_grid(run_dir: str, key: str, bin_updates: int):
    """(battles, decisions at the end of each bin, grid[battle][bin]) for one run. A cell is the
    rate over every episode of that battle in the bin, None where the battle had none."""
    with open(os.path.join(run_dir, "metrics.jsonl")) as f:
        rows = [json.loads(line) for line in f]
    battles = sorted({st for r in rows for st in r["states"]})
    bins = [rows[i:i + bin_updates] for i in range(0, len(rows), bin_updates)]
    grid = []
    for battle in battles:
        cells = []
        for b in bins:
            stats = [r["states"][battle] for r in b if battle in r["states"] and key in r["states"][battle]]
            n = sum(s["episodes"] for s in stats)
            cells.append(sum(s[key] * s["episodes"] for s in stats) / n if n else None)
        grid.append(cells)
    return [b.removesuffix(".state") for b in battles], [b[-1]["decisions"] for b in bins], grid


def by_battle(args):
    key, label = METRICS[args.metric]
    runs = [(os.path.basename(os.path.normpath(r)), *battle_grid(r, key, args.bin)) for r in args.runs]
    runs = [r for r in runs if any(v is not None for row in r[3] for v in row)]
    if not runs:
        sys.exit(f"no run has {key}; runs from before faint counting have only --metric win")
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("ramp", RAMP)
    cmap.set_bad(EMPTY)
    heights = [len(r[1]) for r in runs]
    fig, axes = plt.subplots(len(runs), 1, figsize=(10, 0.36 * sum(heights) + 1.6 * len(runs) + 0.6), sharex=True,
                             facecolor=SURFACE, squeeze=False, gridspec_kw={"height_ratios": heights})
    for ax, (name, battles, ends, grid) in zip(axes[:, 0], runs):
        values = [[float("nan") if v is None else v for v in row] for row in grid]
        # Columns span the decisions they cover, so runs line up on one scale.
        mesh = ax.pcolormesh([0] + ends, range(len(battles) + 1), values, cmap=cmap, vmin=0, vmax=1,
                             edgecolors=SURFACE, linewidth=2)
        ax.set_facecolor(SURFACE)
        ax.set_title(name, loc="left", color=INK, fontsize=11, pad=8)
        ax.set_yticks([i + 0.5 for i in range(len(battles))], [b.replace("_", " ") for b in battles], color=INK_2)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x / 1000:g}k" if x else "0"))
        ax.set_xlabel(f"Decisions trained (each column is {args.bin} updates)")
        ax.xaxis.set_tick_params(labelbottom=True)
        ax.tick_params(length=0)
        for side in ax.spines.values():
            side.set_visible(False)
        for i, row in enumerate(grid):
            seen = [v for v in row if v is not None]
            if seen:
                ax.annotate(f"{seen[0]:.2f} → {seen[-1]:.2f}", (1, i + 0.5), xycoords=("axes fraction", "data"),
                            xytext=(8, 0), textcoords="offset points", va="center", color=INK_2, fontsize=9)
    bar = fig.colorbar(mesh, ax=axes[:, 0], location="bottom", shrink=0.4, aspect=30, pad=0.12)
    bar.set_label(label, color=INK_2)
    bar.outline.set_visible(False)
    fig.suptitle(f"{label} by battle", x=0.01, ha="left", color=INK, fontsize=13, fontweight="bold")
    return fig


def lines(args):
    if len(args.runs) > len(SERIES):
        sys.exit(f"at most {len(SERIES)} runs per chart")
    panels = [("win_rate", "Win rate", args.baseline_win), ("clean_win_rate", "Clean-win rate (won with no faint)", args.baseline_clean)]
    if args.with_return:
        panels.append(("mean_return", "Return (compare only runs with the same reward)", args.baseline_return))
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
    return fig


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run directories, each with a metrics.jsonl")
    ap.add_argument("--state", help="one battle's numbers, such as weak_lead_vs_lileep")
    ap.add_argument("--baseline-win", type=float, help="random play's win rate, drawn as a reference line")
    ap.add_argument("--baseline-clean", type=float, help="random play's clean-win rate")
    ap.add_argument("--baseline-return", type=float, help="random play's return, with --return")
    ap.add_argument("--return", dest="with_return", action="store_true", help="add a return panel")
    ap.add_argument("--by-battle", action="store_true", help="a heatmap per run: battles against training time")
    ap.add_argument("--metric", choices=METRICS, default="clean", help="the heatmap's rate")
    ap.add_argument("--bin", type=int, default=5, help="updates per heatmap column")
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "progress.png"))
    args = ap.parse_args()
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 10, "text.color": INK, "axes.labelcolor": INK_2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": AXIS})
    fig = by_battle(args) if args.by_battle else lines(args)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, dpi=130, facecolor=SURFACE, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
