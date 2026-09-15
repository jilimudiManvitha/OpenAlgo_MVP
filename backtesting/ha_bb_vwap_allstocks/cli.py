import argparse
import json

from .configuration import load_config, resolve


def main():
    parser = argparse.ArgumentParser(
        description="Prepare/run full-history HA/BB/VWAP research; dashboard is read-only."
    )
    parser.add_argument("command", choices=["plan", "run", "serve", "demo"])
    parser.add_argument("--config")
    parser.add_argument("--output")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-days", type=int)
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.output:
        config["output"] = args.output
    if args.max_days is not None and args.max_days <= 0:
        parser.error("max-days must be positive")
    if args.command == "plan":
        from .execution import selected_definitions

        definitions = selected_definitions(config)
        print(
            json.dumps(
                {
                    "status": "not_run",
                    "source_opened": False,
                    "start": config["start"],
                    "end": config["end"],
                    "source": str(resolve(config["source"])),
                    "output": str(resolve(config["output"])),
                    "strategies": len(definitions),
                    "paths": config["paths"],
                    "universe": "all available source stocks"
                    if not config["symbols"]
                    else config["symbols"],
                    "groupings": [
                        "day",
                        "week",
                        "month",
                        "quarter",
                        "half_year",
                        "year",
                        "five_year",
                        "all",
                    ],
                    "execution": "Only the run command executes market-data backtests; plan/serve do not.",
                },
                indent=2,
            )
        )
    elif args.command == "run":
        from .runner import run

        run(config, resume=args.resume, max_days=args.max_days)
    elif args.command == "serve":
        from .dashboard import serve

        serve(resolve(config["output"]), args.port)
    else:
        from .demo import create_demo

        output = resolve(args.output or "backtesting/ha_bb_vwap_allstocks/demo_output")
        create_demo(output)
        print(f"Synthetic demo written to {output}; no market source was opened.")


if __name__ == "__main__":
    main()
