import argparse
import json
import logging
import os

from agent.sender import enroll_soc, load_config, send_report, set_api_key


def main():
    parser = argparse.ArgumentParser(
        description="Send Android system information to a remote API."
    )
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        help="Path to config.json",
    )
    parser.add_argument("--loop", action="store_true", help="Send continuously")
    parser.add_argument(
        "--set-api-key",
        metavar="KEY",
        help="Store the Dolibarr API key encrypted in config.json",
    )
    parser.add_argument(
        "--enroll",
        metavar="CODE",
        help="Enroll this device with a one-time code from the thirdparty card",
    )
    parser.add_argument(
        "--confirm-reassign",
        action="store_true",
        help="Confirm reassignment when enrolling an already-assigned device",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)

    if args.set_api_key is not None:
        set_api_key(config, args.config, args.set_api_key)
        print("Cle API stockee chiffree dans", args.config)
        return

    if args.enroll is not None:
        ok, message, need_confirm = enroll_soc(
            config, args.enroll, args.config, confirm_reassign=args.confirm_reassign
        )
        print(message)
        if need_confirm:
            print("Relancez avec --confirm-reassign pour confirmer la reaffectation.")
        return

    if args.loop:
        import time

        time.sleep(config.get("initial_delay_seconds", 30))
        while True:
            try:
                send_report(config)
            except Exception as exc:
                logging.getLogger("run").error("Report failed: %s", exc)
            time.sleep(config.get("poll_interval_seconds", 14400))
    else:
        payload = send_report(config)
        print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
