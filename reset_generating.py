"""Stop hook — clears the generating lock for the current tmux pane."""

from lib import Config, Session, TmuxClient, NotInTmuxError


def main() -> None:
    try:
        pane_id = TmuxClient().get_pane_id()
    except NotInTmuxError:
        return
    Session(pane_id, Config().base_dir).clear_lock()


if __name__ == "__main__":
    main()
