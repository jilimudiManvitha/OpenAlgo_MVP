"""Run the frozen four-strategy selection and build findings upon completion."""

import argparse

from .comparison import build
from .configuration import HERE, load_config, resolve
from .runner import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config", default=str(HERE / "selected_four.json"))
    args = parser.parse_args()
    config = load_config(args.config)
    if set(config["strategy_ids"]) != {"S092", "S109", "S299", "S305"}:
        parser.error("This wrapper requires exactly S092, S109, S299 and S305")
    result = run(config, resume=args.resume)
    if result["completed_days"] == result["planned_days"]:
        output = resolve(config["output"])
        build(output)
        print(f"Final findings: {output / 'comparison' / 'index.html'}", flush=True)


if __name__ == "__main__":
    main()
