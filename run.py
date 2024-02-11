#!/usr/bin/env python3

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import textwrap
import time
import traceback
from base64 import b64decode
from typing import List, Tuple, Union

from musicbot.constants import (
    DEFAULT_LOGS_KEPT,
    DEFAULT_LOGS_ROTATE_FORMAT,
    MAXIMUM_LOGS_LIMIT,
)
from musicbot.constants import VERSION as BOTVERSION
from musicbot.exceptions import HelpfulError, RestartSignal, TerminateSignal
from musicbot.utils import (
    rotate_log_files,
    set_logging_level,
    set_logging_max_kept_logs,
    set_logging_rotate_date_format,
    setup_loggers,
    shutdown_loggers,
)

# protect dependency import from stopping the launcher
try:
    import aiohttp
except ImportError:
    pass

log = logging.getLogger("musicbot.launcher")


class GIT:
    @classmethod
    def works(cls, raise_instead: bool = False) -> bool:
        """
        Checks for output from git --version to verify git can be run.

        :param: raise_instead:  Return True on success but raise Runtime error otherwise.

        :raises:  RuntimeError  if `raise_instead` is set True.
        """
        try:
            git_bin = shutil.which("git")
            if not git_bin:
                if raise_instead:
                    raise RuntimeError(
                        "Cannot locate `git` executable in environment path."
                    )
                return False
            return bool(subprocess.check_output([git_bin, "--version"]))
        except (
            OSError,
            ValueError,
            PermissionError,
            FileNotFoundError,
            subprocess.CalledProcessError,
        ) as e:
            if raise_instead:
                raise RuntimeError(
                    f"Cannot execute `git` commands due to an error:  {str(e)}"
                ) from e
            return False

    @classmethod
    def show_branch(cls) -> str:
        """
        Runs `git rev-parse --abbrev-ref HEAD` to get the current branch name.
        Will return an empty string if running the command fails.
        """
        try:
            git_bin = shutil.which("git")
            if not git_bin:
                log.warning("Could not find git executable.")
                return ""

            gitbytes = subprocess.check_output(
                [git_bin, "rev-parse", "--abbrev-ref", "HEAD"]
            )
            branch = gitbytes.decode("utf8").strip()

            return branch
        except (OSError, ValueError, subprocess.CalledProcessError):
            return ""

    @classmethod
    def check_updates(cls) -> Tuple[str, str]:
        """
        Runs `git fetch --dry-run` and extracts the commit IDs.
        If the command fails or no commit IDs are found, this
        will return empty strings rather than raise errors.
        """
        branch = cls.show_branch()
        if not branch:
            return ("", "")

        try:
            commit_at = ""
            commit_to = ""
            git_bin = shutil.which("git")
            if not git_bin:
                return ("", "")

            gitbytes = subprocess.check_output([git_bin, "fetch", "--dry-run"])
            lines = gitbytes.decode("utf8").split("\n")
            for line in lines:
                parts = line.split()
                if branch in parts:
                    commits = line.strip().split(" ", maxsplit=1)[0]
                    commit_at, commit_to = commits.split("..")
                    break

            return (commit_at, commit_to)
        except (OSError, ValueError, subprocess.CalledProcessError):
            return ("", "")

    @classmethod
    def run_upgrade_pull(cls) -> None:
        """Runs `git pull` in the current working directory."""
        cls.works(raise_instead=True)

        log.info("Attempting to upgrade with `git pull` on current path.")
        try:
            git_bin = shutil.which("git")
            if not git_bin:
                raise FileNotFoundError("Could not locate `git` executable on path.")
            raw_data = subprocess.check_output([git_bin, "pull"])
            git_data = raw_data.decode("utf8").strip()
            log.info("Result of git pull:  %s", git_data)
        except (
            OSError,
            UnicodeError,
            PermissionError,
            FileNotFoundError,
            subprocess.CalledProcessError,
        ):
            log.exception("Upgrade failed, you need to run `git pull` manually.")


class PIP:
    @classmethod
    def run(cls, command: str, check_output: bool = False) -> Union[bytes, int]:
        """Runs a pip command using `sys.exectutable -m pip` through subprocess.
        Given `command` is split before it is passed, so quoted items will not work.
        """
        if not cls.works():
            raise RuntimeError("Cannot execute pip.")

        try:
            return cls.run_python_m(command.split(), check_output=check_output)
        except subprocess.CalledProcessError as e:
            return e.returncode
        except (OSError, PermissionError, FileNotFoundError):
            log.exception("Error using -m method")
        return 0

    @classmethod
    def run_python_m(
        cls, args: List[str], check_output: bool = False
    ) -> Union[bytes, int]:
        """
        Use subprocess check_call or check_output to run a pip module
        command using the `args` as additional arguments to pip.
        The returned value of the call is returned from this method.

        :param: check_output:  Use check_output rather than check_call.
        """
        if check_output:
            return subprocess.check_output(
                [sys.executable, "-m", "pip"] + args,
                stderr=subprocess.DEVNULL,
            )
        return subprocess.check_call(
            [sys.executable, "-m", "pip"] + args,
            stdout=subprocess.DEVNULL,
        )

    @classmethod
    def run_install(
        cls, cmd: str, quiet: bool = False, check_output: bool = False
    ) -> Union[bytes, int]:
        """
        Runs pip install command and returns the command exist status.

        :param: cmd:  a string of arguments passed to `pip install`.
        :param: quiet:  attempt to silence output using -q command flag.
        :param: check_output:  return command output instead of exit code.
        """
        q_flag = "-q " if quiet else ""
        return cls.run(f"install {q_flag}{cmd}", check_output)

    @classmethod
    def works(cls) -> bool:
        """Checks for output from pip --version to verify pip can be run."""
        try:
            rcode = cls.run_python_m(["--version"])
            if rcode == 0:
                return True
            return False
        except subprocess.CalledProcessError:
            log.exception("PIP failed while calling sub-process.")
            return False
        except PermissionError:
            log.exception("PIP failed due to Permissions Error.")
            return False
        except FileNotFoundError:
            log.exception(
                "PIP failed due to missing Python executable?  (%s)",
                sys.executable,
            )
            return False
        except OSError:
            log.exception("PIP failed due to OSError.")
            return False

    @classmethod
    def check_updates(cls) -> int:
        """
        Runs `pip install -U -r ./requirements.txt --quiet --dry-run --report -`
        and returns the number of packages that could be updated.
        """
        updata = cls.run_install(
            "-U -r ./requirements.txt --quiet --dry-run --report -",
            check_output=True,
        )
        try:
            if isinstance(updata, bytes):
                pip_data = json.loads(updata)
                return len(pip_data.get("install", []))
        except json.JSONDecodeError:
            log.warning("Could not decode pip update report JSON.")

        return 0

    @classmethod
    def run_upgrade_requirements(cls, get_output: bool = False) -> Union[str, int]:
        """
        Uses a subprocess call to run python using sys.executable.
        Runs `pip install --no-warn-script-location --no-input -U -r ./requirements.txt`
        This method attempts to catch all exceptions and ensure a return value.

        :param: get_output:  Return the process output rather than its exit code.
            If set True, and an exception is caught, this will return the string "[[ProcessException]]"
            If set False and an exception is caught, this will return int -255

        :returns:  process exit code, where 0 is assumed success.
        """
        if not cls.works():
            raise RuntimeError("Cannot locate or execute python -m pip")

        log.info(
            "Attempting to upgrade with `pip install --upgrade -r requirements.txt` on current path..."
        )
        try:
            raw_data = cls.run_python_m(
                [
                    "install",
                    "--no-warn-script-location",
                    "--no-input",
                    "-U",
                    "-r",
                    "requirements.txt",
                ],
                check_output=get_output,
            )
            if isinstance(raw_data, bytes):
                pip_data = raw_data.decode("utf8").strip()
                log.info("Result of pip upgrade:\n%s", pip_data)
                if get_output:
                    return pip_data

            if isinstance(raw_data, int):
                log.info("Result exit code from pip upgrade: %s", raw_data)
                return raw_data

            # if somehow raw_data is not int or bytes.
            if get_output:
                return "[[OutputTypeException]]"
            return -255
        except (
            PermissionError,
            FileNotFoundError,
            OSError,
            UnicodeError,
            subprocess.CalledProcessError,
        ):
            log.exception(
                "Upgrade failed to execute or we could not understand the output"
            )
            log.warning(
                "You may need to run `pip install --upgrade -r requirements.txt` manually."
            )

            if get_output:
                return "[[ProcessException]]"
            return -255


def bugger_off(msg: str = "Press enter to continue . . .", code: int = 1) -> None:
    """Make the console wait for the user to press enter/return."""
    input(msg)
    sys.exit(code)


def sanity_checks(args: argparse.Namespace, optional: bool = True) -> None:
    """
    Run a collection of pre-startup checks to either automatically correct
    issues or inform the user of how to correct them.

    :param: optional:  Toggle optional start up checks.
    """
    log.info("Starting sanity checks")
    """Required Checks"""
    # Make sure we're on Python 3.8+
    req_ensure_py3()

    # Make sure we're in a writable env
    req_ensure_env()

    # Make our folders if needed
    pathlib.Path("data").mkdir(exist_ok=True)

    # For rewrite only
    req_check_deps()

    log.info("Required checks passed.")

    """Optional Checks"""
    if not optional:
        return

    # Check disk usage
    opt_check_disk_space()

    # Display an update check, if enabled.
    if not args.no_update_check:
        opt_check_updates()

    log.info("Optional checks passed.")


def req_ensure_py3() -> None:
    """
    Verify the current running version of Python and attempt to find a
    suitable minimum version in the system if the running version is too old.
    """
    log.info("Checking for Python 3.8+")

    if sys.version_info < (3, 8):
        log.warning(
            "Python 3.8+ is required. This version is %s", sys.version.split()[0]
        )
        log.warning("Attempting to locate Python 3.8...")
        # Should we look for other versions than min-ver?

        pycom = None

        if sys.platform.startswith("win"):
            pycom = shutil.which("py.exe")
            if not pycom:
                log.warning("Could not locate py.exe")

            try:
                subprocess.check_output([pycom, "-3.8", '-c "exit()"'])
                pycom = f"{pycom} -3.8"
            except (
                OSError,
                PermissionError,
                FileNotFoundError,
                subprocess.CalledProcessError,
            ):
                log.warning("Could not execute `py.exe -3.8` ")
                pycom = None

            if pycom:
                log.info("Python 3 found.  Launching bot...")
                os.system(f"start cmd /k {pycom} run.py")
                sys.exit(0)

        else:
            log.info('Trying "python3.8"')
            pycom = shutil.which("python3.8")
            if not pycom:
                log.warning("Could not locate python3.8 on path.")

            try:
                subprocess.check_output([pycom, '-c "exit()"'])
            except (
                OSError,
                PermissionError,
                FileNotFoundError,
                subprocess.CalledProcessError,
            ):
                pycom = None

            if pycom:
                log.info(
                    "\nPython 3.8 found.  Re-launching bot using: %s run.py\n", pycom
                )
                os.execlp(pycom, pycom, "run.py")

        log.critical(
            "Could not find Python 3.8 or higher.  Please run the bot using Python 3.8"
        )
        bugger_off()


def req_check_deps() -> None:
    """
    Check that we have the required dependency modules at the right versions.
    """
    try:
        import discord  # pylint: disable=import-outside-toplevel

        if discord.version_info.major < 2:
            log.critical(
                "This version of MusicBot requires a newer version of discord.py. "
                "Your version is %s. Try running update.py.",
                discord.__version__,
            )
            bugger_off()
    except ImportError:
        # if we can't import discord.py, an error will be thrown later down the line anyway
        pass


def req_ensure_env() -> None:
    """
    Inspect the environment variables, validating and updating values where needed.
    """
    log.info("Ensuring we're in the right environment")

    if os.environ.get("APP_ENV") != "docker" and not os.path.isdir(
        b64decode("LmdpdA==").decode("utf-8")
    ):
        log.critical(
            b64decode(
                "Qm90IHdhc24ndCBpbnN0YWxsZWQgdXNpbmcgR2l0LiBSZWluc3RhbGwgdXNpbmcgaHR0cDovL2JpdC5seS9tdXNpY2JvdGRvY3Mu"
            ).decode("utf-8")
        )
        bugger_off()

    try:
        if not os.path.isdir("config"):
            raise RuntimeError('folder "config" not found')

        if not os.path.isdir("musicbot"):
            raise RuntimeError('folder "musicbot" not found')

        if not os.path.isfile("musicbot/__init__.py"):
            raise RuntimeError("musicbot folder is not a Python module")

        if not importlib.util.find_spec("musicbot"):
            raise RuntimeError("musicbot module is not importable")
    except RuntimeError as e:
        log.critical("Failed environment check, %s", e)
        bugger_off()

    try:
        os.mkdir("musicbot-test-folder")
    except (
        OSError,
        FileExistsError,
        PermissionError,
        IsADirectoryError,
    ):
        log.critical("Current working directory does not seem to be writable")
        log.critical("Please move the bot to a folder that is writable")
        bugger_off()
    finally:
        shutil.rmtree("musicbot-test-folder", True)

    if sys.platform.startswith("win"):
        log.info("Adding local bins/ folder to path")
        os.environ["PATH"] += ";" + os.path.abspath("bin/")
        sys.path.append(os.path.abspath("bin/"))  # might as well


def opt_check_disk_space(warnlimit_mb: int = 200) -> None:
    """
    Performs and optional check of system disk storage space to warn the
    user if the bot might gobble that remaining space with downloads later.
    """
    if shutil.disk_usage(".").free < warnlimit_mb * 1024 * 2:
        log.warning(
            "Less than %sMB of free space remains on this device",
            warnlimit_mb,
        )


def opt_check_updates() -> None:
    """
    Runs a collection of git and pip commands and logs if updates are available.
    """
    log.info("\nChecking for updates to MusicBot or dependencies...")
    needs_update = False
    if GIT.works():
        git_branch = GIT.show_branch()
        commit_at, commit_to = GIT.check_updates()
        if commit_at and commit_to:
            log.warning(
                "MusicBot updates are available through `git` command.\n"
                "Your current branch is:  %s\n"
                "The latest commit ID is:  %s",
                git_branch,
                commit_to,
            )
            needs_update = True
        else:
            log.info("No MusicBot updates available via `git` command.")
    else:
        log.warning(
            "Could not check for updates using `git` commands.  You should check manually."
        )

    if PIP.works():
        # TODO: should probably list / prioritize packages.
        package_count = PIP.check_updates()
        if package_count:
            log.warning(
                "There may be updates for dependency packages. "
                "PIP reports %s package(s) could be installed.",
                package_count,
            )
            needs_update = True
        else:
            log.info("No dependency updates available via `pip` command.")
    else:
        log.warning(
            "Could not check for updates using `pip` commands.  You should check manually."
        )
    if needs_update:
        log.info(
            "You can run a guided update by using the command:\n    %s ./update.py",
            sys.executable,
        )


def parse_cli_args() -> argparse.Namespace:
    """
    Parse command line arguments and do reasonable checks and assignments.

    :returns:  Command line arguments parsed via argparse.
    """

    # define a few custom arg validators.
    def kept_logs_int(value: str) -> int:
        """Validator for log rotation limits."""
        try:
            val = int(value)
            if val > MAXIMUM_LOGS_LIMIT:
                raise ValueError("Value is above the maximum limit.")
            if val <= -1:
                raise ValueError("Value must not be negative.")
            return val
        except (TypeError, ValueError) as e:
            raise argparse.ArgumentTypeError(
                f"Value for Max Logs Kept must be a number from 0 to {MAXIMUM_LOGS_LIMIT}",
            ) from e

    def log_levels_int(level_name: str) -> int:
        """Validator for log level name to existing level int."""
        level_name = level_name.upper()
        try:
            val = getattr(logging, level_name, None)
            if not isinstance(val, int):
                raise TypeError(f"Log level '{level_name}' is not available.")
            return val
        except (TypeError, ValueError) as e:
            raise argparse.ArgumentTypeError(
                "Log Level must be one of:  CRITICAL, ERROR, WARNING, INFO, DEBUG, "
                "VOICEDEBUG, FFMPEG, NOISY, or EVERYTHING",
            ) from e

    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
        Launch a music playing discord bot built using discord.py, youtubeDL, and ffmpeg.
        Available via Github:
          https://github.com/Just-Some-Bots/MusicBot
        """
        ),
        epilog=textwrap.dedent(
            """\
        For more help and support with this bot, join our discord:
          https://discord.gg/bots

        This software is provided under the MIT License.
        See the `LICENSE` text file for complete details.
        """
        ),
    )

    # Show Version and exit option.
    ap.add_argument(
        "-V",
        "--version",
        dest="show_version",
        action="store_true",
        help="Print the MusicBot version information and exit.",
    )

    # No Startup Checks option.
    ap.add_argument(
        "--no-checks",
        dest="do_start_checks",
        action="store_false",
        help="Skip all startup checks, including the update check.",
    )

    ap.add_argument(
        "--no-update-check",
        dest="no_update_check",
        action="store_true",
        help="Skip only the update check at startup.",
    )

    ap.add_argument(
        "--no-install-deps",
        dest="no_install_deps",
        action="store_true",
        help="Disable MusicBot from trying to install dependencies when it cannot import them.",
    )

    # Log related options
    ap.add_argument(
        "--logs-kept",
        dest="keep_n_logs",
        default=DEFAULT_LOGS_KEPT,
        type=kept_logs_int,
        help=f"Specify how many log files to keep, between 0 and {MAXIMUM_LOGS_LIMIT} inclusive."
        f" (Default: {DEFAULT_LOGS_KEPT})",
    )
    ap.add_argument(
        "--log-level",
        dest="log_level",
        default="NOTSET",
        type=log_levels_int,
        help="Override the log level settings set in config. Must be one of: "
        "CRITICAL, ERROR, WARNING, INFO, DEBUG, VOICEDEBUG, FFMPEG, "
        "NOISY, or EVERYTHING   (Default: NOTSET)",
    )
    ap.add_argument(
        "--log-rotate-fmt",
        dest="old_log_fmt",
        default=DEFAULT_LOGS_ROTATE_FORMAT,
        type=str,
        help="Override the default date format used when rotating log files. "
        "This should contain values compatible with strftime().  "
        f"(Default:  '{DEFAULT_LOGS_ROTATE_FORMAT.replace('%', '%%')}')",
    )

    # TODO: maybe more arguments for other things:
    # --config-dir      force this directory for config data (all files)
    # --config-file     load config from this file, but default for other configs.
    # --max-dl-threads  max number of threads to use for ytdlp extractions and downloads.
    # --bind-to-ip      IP address used by ytdlp as the source for requests.
    # -4 --only-ipv4    Force binding to all available IPv4 addresses. Value:  0.0.0.0
    # -6 --only-ipv6    Force binding to all available IPv6 addresses. Value:  ::

    args = ap.parse_args()

    # Show version and exit.
    if args.show_version:
        print(f"Just-Some-Bots/MusicBot\nVersion:  {BOTVERSION}\n")
        sys.exit(0)

    if -1 < args.keep_n_logs <= MAXIMUM_LOGS_LIMIT:
        set_logging_max_kept_logs(args.keep_n_logs)

    if args.log_level != logging.NOTSET:
        set_logging_level(args.log_level, override=True)

    if args.old_log_fmt != DEFAULT_LOGS_ROTATE_FORMAT:
        set_logging_rotate_date_format(args.old_log_fmt)

    return args


def respawn_bot_process(pybin: str = "") -> None:
    """
    Use a platform dependent method to restart the bot process, without
    an external process/service manager.
    This uses either the given `pybin` executable path or sys.executable
    to run the bot using the arguments currently in sys.argv

    This function attempts to make sure all buffers are flushed and logging
    is shut down before restarting the new process.

    On Linux/Unix-style OS this will use sys.execlp to replace the process
    while keeping the existing PID.

    On Windows OS this will use subprocess.Popen to create a new console
    where the new bot is started, with a new PID, and exit this instance.
    """
    if not pybin:
        pybin = sys.executable
    exec_args = [pybin] + sys.argv

    shutdown_loggers()
    rotate_log_files()

    sys.stdout.flush()
    sys.stderr.flush()
    logging.shutdown()

    if os.name == "nt":
        # On Windows, this creates a new process window that dies when the script exits.
        # Seemed like the best way to avoid a pile of processes While keeping clean output in the shell.
        # There is seemingly no way to get the same effect as os.exec* on unix here in windows land.
        # The moment we end our existing instance, control is returned to the starting shell.
        with subprocess.Popen(
            exec_args,
            creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
        ):
            log.debug("Opened new MusicBot instance.  This terminal can now be closed!")
        sys.exit(0)
    else:
        # On Unix/Linux/Mac this should immediately replace the current program.
        # No new PID, and the babies all get thrown out with the bath.  Kinda dangerous...
        # We need to make sure files and things are closed before we do this.
        os.execlp(exec_args[0], *exec_args)


async def main(
    args: argparse.Namespace,
) -> Union[RestartSignal, TerminateSignal, None]:
    """
    All of the MusicBot starts here.

    :param: args:  some arguments parsed from the command line.

    :returns:  Oddly, returns rather than raises a *Signal or nothing.
    """
    # TODO: this function may not need to be async.

    # Handle startup checks, if they haven't been skipped.
    if args.do_start_checks:
        sanity_checks(args)
    else:
        log.info("Skipped startup checks.")

    exit_signal: Union[RestartSignal, TerminateSignal, None] = None
    tried_requirementstxt = False
    use_certifi = False
    tryagain = True

    loops = 0
    max_wait_time = 60

    while tryagain:
        # Maybe I need to try to import stuff first, then actually import stuff
        # It'd save me a lot of pain with all that awful exception type checking

        m = None
        try:
            from musicbot import MusicBot  # pylint: disable=import-outside-toplevel

            m = MusicBot(use_certifi=use_certifi)
            await m.run()

        except (
            ssl.SSLCertVerificationError,
            aiohttp.client_exceptions.ClientConnectorCertificateError,
        ) as e:
            if isinstance(
                e, aiohttp.client_exceptions.ClientConnectorCertificateError
            ) and isinstance(e.__cause__, ssl.SSLCertVerificationError):
                e = e.__cause__
            else:
                log.critical(
                    "Certificate error is not a verification error, not trying certifi and exiting."
                )
                break

            # In case the local trust store does not have the cert locally, we can try certifi.
            # We don't want to patch working systems with a third-party trust chain outright.
            # These verify_code values come from OpenSSL:  https://www.openssl.org/docs/man1.0.2/man1/verify.html
            if e.verify_code == 20:  # X509_V_ERR_UNABLE_TO_GET_ISSUER_CERT_LOCALLY
                if use_certifi:
                    log.exception(
                        "Could not get Issuer Certificate even with certifi!\n"
                        "Try running:  %s -m pip install --upgrade certifi ",
                        sys.executable,
                    )
                    log.warning(
                        "To easily add a certificate to Windows trust store, \n"
                        "you can open the failing site in Microsoft Edge or IE...\n"
                    )
                    break

                log.warning(
                    "Could not get Issuer Certificate from default trust store, trying certifi instead."
                )
                use_certifi = True
                continue

        except SyntaxError:
            if "-dirty" in BOTVERSION:
                log.exception("Syntax error (version is dirty, did you edit the code?)")
            else:
                log.exception("Syntax error (this is a bug, not your fault)")
            break

        except ImportError:
            if args.no_install_deps:
                log.error(
                    "Error importing MusicBot or it's dependency packages.\n"
                    "The `--no-install-deps` option is set, so MusicBot will exit now."
                )
                log.exception("This is the exception which caused the above error: ")
                break

            if not PIP.works():
                log.critical(
                    "MusicBot could not import dependency modules and we cannot run `pip` automatically!\n"
                    "You will need to manually install `pip` package for your version of python.\n"
                )
                log.warning(
                    "If you already installed `pip` but still get this error:\n"
                    " - Check that you installed it for this python version: %s\n"
                    " - Check installed packages are accessible to the user running MusicBot",
                    sys.version.split(maxsplit=1)[0],
                )
                break

            if not tried_requirementstxt:
                tried_requirementstxt = True

                log.exception("Error importing dependencies while starting bot.")
                err = PIP.run_upgrade_requirements(get_output=True)

                if err:  # TODO: add the specific error check back.
                    # The proper thing to do here is tell the user to fix
                    # their install, not help make it worse or insecure.
                    # Comprehensive return codes aren't really a feature of pip,
                    # If we need to read the log, then so does the user.
                    print()
                    log.critical(
                        "This is not recommended! You can try to %s to install dependencies anyways.",
                        ["use sudo", "run as admin"][sys.platform.startswith("win")],
                    )
                    break

                print()
                log.info("Ok lets hope it worked")
                print()
            else:
                log.error(
                    "MusicBot got an ImportError after trying to install packages. MusicBot must exit..."
                )
                log.exception("The exception which caused the above error: ")
                break

        except HelpfulError as e:
            log.info(e.message)
            break

        except TerminateSignal as e:
            exit_signal = e
            break

        except RestartSignal as e:
            if e.get_name() == "RESTART_SOFT":
                loops = 0
            else:
                exit_signal = e
                break

        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("Error starting bot")

        finally:
            if m and (m.session or m.http.connector):
                # in case we never made it to m.run(), ensure cleanup.
                log.debug("Doing cleanup late.")
                await m.shutdown_cleanup()

            if (not m or not m.init_ok) and not use_certifi:
                if any(sys.exc_info()):
                    # How to log this without redundant messages...
                    log.warning(
                        "There are some exceptions that may not have been handled..."
                    )
                    log.debug(
                        "Traceback output:\n%s",
                        "".join(traceback.format_exc()),
                    )
                tryagain = False

            loops += 1

        sleeptime = min(loops * 2, max_wait_time)
        if sleeptime:
            log.info("Restarting in %s seconds...", sleeptime)
            time.sleep(sleeptime)

    print()
    log.info("All done.")
    return exit_signal


if __name__ == "__main__":
    # take care of loggers right away
    setup_loggers()

    # parse arguments before any logs, so --help does not make an empty log.
    cli_args = parse_cli_args()

    # Log file creation is deferred until this first write.
    log.info("Loading MusicBot version:  %s", BOTVERSION)
    log.info("Log opened:  %s", time.ctime())

    # Check if run.py is in the current working directory.
    run_py_dir = os.path.dirname(os.path.realpath(__file__))
    if run_py_dir != os.getcwd():
        # if not, verify musicbot and .git folders exists and change directory.
        run_mb_dir = pathlib.Path(run_py_dir).joinpath("musicbot")
        run_git_dir = pathlib.Path(run_py_dir).joinpath(".git")
        if run_mb_dir.is_dir() and run_git_dir.is_dir():
            log.warning("Changing working directory to:  %s", run_py_dir)
            os.chdir(run_py_dir)
        else:
            log.critical(
                "Cannot start the bot!  You started `run.py` in the wrong directory"
                " and we could not locate `musicbot` and `.git` folders to verify"
                " a new directory location."
            )
            log.error(
                "For best results, start `run.py` from the same folder you cloned MusicBot into.\n"
                "If you did not use git to clone the repository, you are strongly urged to."
            )
            time.sleep(3)  # make sure they see the message.
            sys.exit(127)

    # py3.8 made ProactorEventLoop default on windows.
    # Now we need to make adjustments for a bug in aiohttp :)
    loop = asyncio.get_event_loop_policy().get_event_loop()
    try:
        exit_sig = loop.run_until_complete(main(cli_args))
    except KeyboardInterrupt:
        # TODO: later this will probably get more cleanup so we can
        # close other things more proper like too.
        log.info("\nCaught a keyboard interrupt signal.")
        shutdown_loggers()
        rotate_log_files()
        raise

    if exit_sig:
        if isinstance(exit_sig, RestartSignal):
            if exit_sig.get_name() == "RESTART_FULL":
                respawn_bot_process()
            elif exit_sig.get_name() == "RESTART_UPGRADE_ALL":
                PIP.run_upgrade_requirements()
                GIT.run_upgrade_pull()
                respawn_bot_process()
            elif exit_sig.get_name() == "RESTART_UPGRADE_PIP":
                PIP.run_upgrade_requirements()
                respawn_bot_process()
            elif exit_sig.get_name() == "RESTART_UPGRADE_GIT":
                GIT.run_upgrade_pull()
                respawn_bot_process()
        elif isinstance(exit_sig, TerminateSignal):
            shutdown_loggers()
            rotate_log_files()
            sys.exit(exit_sig.exit_code)
