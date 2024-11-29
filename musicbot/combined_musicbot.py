import argparse
import pathlib
import sys
from typing import Any, Dict, NoReturn, Union

BASE_WRITE_PATH: str = ""


def parse_write_base_arg() -> None:
    """
    Handles command line arguments for base directory early.
    """
    arg39: Dict[str, Any] = {}
    if sys.version_info >= (3, 9):
        arg39 = {"exit_on_error": False}

    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="",
        epilog="",
        usage="",
        add_help=False,
        allow_abbrev=False,
        **arg39,
    )

    # Make sure argparser does not exit or print.
    def _error(message: str) -> NoReturn:  # type: ignore[misc]
        print("Write Base Argument Error:  %s", message)

    ap.error = _error  # type: ignore[method-assign]

    ap.add_argument(
        "--write-dir",
        dest="global_writes_basedir",
        type=str,
        help="",
        default="",
    )

    args, _ = ap.parse_known_args()

    if args.global_writes_basedir:
        basedir = pathlib.Path(args.global_writes_basedir).resolve()
        basedir.mkdir(parents=True, exist_ok=True)
        set_write_base(basedir)


def set_write_base(base_path: Union[str, pathlib.Path]) -> None:
    """Update the base write path for musicbot"""
    global BASE_WRITE_PATH  # pylint: disable=global-statement
    BASE_WRITE_PATH = str(base_path)


def get_write_base() -> str:
    """Get the string version of the base write path."""
    return BASE_WRITE_PATH


def write_path(path: Union[str, pathlib.Path]) -> pathlib.Path:
    """
    Get a pathlib.Path object for path, with the global write base path if one was set.
    """
    if BASE_WRITE_PATH:
        return pathlib.Path(BASE_WRITE_PATH).resolve().joinpath(path)
    return pathlib.Path(path).resolve()
import json
import logging
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Tuple

from .constants import DEFAULT_COMMAND_ALIAS_FILE, EXAMPLE_COMMAND_ALIAS_FILE
from .exceptions import HelpfulError

log = logging.getLogger(__name__)

RawAliasJSON = Dict[str, Any]
CommandTuple = Tuple[str, str]  # (cmd, args)
AliasTuple = Tuple[str, str]  # (alias, args)
AliasesDict = Dict[str, CommandTuple]  # {alias: (cmd, args)}
CommandDict = DefaultDict[str, List[AliasTuple]]  # {cmd: [(alias, args),]}


class Aliases:
    """
    Aliases class provides a method of duplicating commands under different names or
    providing reduction in keystrokes for multi-argument commands.
    Command alias with conflicting names will overload each other, it is up to
    the user to avoid configuring aliases with conflicts.
    """

    def __init__(self, aliases_file: Path, nat_cmds: List[str]) -> None:
        """
        Handle locating, initializing, loading, and validation of command aliases.
        If given `aliases_file` is not found, examples will be copied to the location.

        :raises: musicbot.exceptions.HelpfulError
            if loading fails in some known way.
        """
        # List of "natural" commands to allow.
        self.nat_cmds: List[str] = nat_cmds
        # File Path used to locate and load the alias json.
        self.aliases_file: Path = aliases_file
        # "raw" dict from json file.
        self.aliases_seed: RawAliasJSON = AliasesDefault.aliases_seed
        # Simple aliases
        self.aliases: AliasesDict = AliasesDefault.complex_aliases
        # Reverse lookup list generated when loading aliases.
        self.cmd_aliases: CommandDict = defaultdict(list)

        # find aliases file
        if not self.aliases_file.is_file():
            example_aliases = Path(EXAMPLE_COMMAND_ALIAS_FILE)
            if example_aliases.is_file():
                shutil.copy(str(example_aliases), str(self.aliases_file))
                log.warning("Aliases file not found, copying example_aliases.json")
            else:
                raise HelpfulError(
                    # fmt: off
                    "Error while loading aliases.\n"
                    "\n"
                    "Problem:\n"
                    "  Your aliases files (aliases.json & example_aliases.json) are missing.\n"
                    "\n"
                    "Solution:\n"
                    "  Replace the alias config file(s) or copy them from:\n"
                    "    https://github.com/Just-Some-Bots/MusicBot/",
                    # fmt: on
                )

        # parse json
        self.load()

    def load(self) -> None:
        """
        Attempt to load/decode JSON and determine which version of aliases we have.
        """
        # parse json
        try:
            with self.aliases_file.open() as f:
                self.aliases_seed = json.load(f)
        except OSError as e:
            log.error(
                "Failed to load aliases file:  %s",
                self.aliases_file,
                exc_info=e,
            )
            self.aliases_seed = AliasesDefault.aliases_seed
            return
        except json.JSONDecodeError as e:
            log.error(
                "Failed to parse aliases file:  %s\n"
                "Ensure the file contains valid JSON and restart the bot.",
                self.aliases_file,
                exc_info=e,
            )
            self.aliases_seed = AliasesDefault.aliases_seed
            return

        # clear aliases data
        self.aliases.clear()
        self.cmd_aliases.clear()

        # Create an alias-to-command map from the JSON.
        for cmd, aliases in self.aliases_seed.items():
            # ignore comments
            if cmd.lower() in ["--comment", "--comments"]:
                continue

            # check for spaces, and handle args in cmd alias if they exist.
            cmd_args = ""
            if " " in cmd:
                cmd_bits = cmd.split(" ", maxsplit=1)
                if len(cmd_bits) > 1:
                    cmd = cmd_bits[0]
                    cmd_args = cmd_bits[1].strip()
                cmd = cmd.strip()

            # ensure command name is valid.
            if cmd not in self.nat_cmds:
                log.error(
                    "Aliases skipped for non-existent command:  %(command)s  ->  %(aliases)s",
                    {"command": cmd, "aliases": aliases},
                )
                continue

            # ensure alias data uses valid types.
            if not isinstance(cmd, str) or not isinstance(aliases, list):
                log.error(
                    "Alias(es) skipped for invalid alias data:  %(command)s  ->  %(aliases)s",
                    {"command": cmd, "aliases": aliases},
                )
                continue

            # Loop over given aliases and associate them.
            for alias in aliases:
                alias = alias.lower()
                if alias in self.aliases:
                    log.error(
                        "Alias `%(alias)s` skipped as already exists on command:  %(command)s",
                        {"alias": alias, "command": self.aliases[alias]},
                    )
                    continue

                self.aliases.update({alias: (cmd, cmd_args)})
                self.cmd_aliases[cmd].append((alias, cmd_args))

    def save(self) -> None:
        """
        Save the aliases in memory to the disk.

        :raises: OSError if open for write fails.
        :raises: RuntimeError if something fails to encode.
        """
        try:
            with self.aliases_file.open(mode="w") as f:
                json.dump(self.aliases_seed, f, indent=4, sort_keys=True)
        except (ValueError, TypeError, RecursionError) as e:
            raise RuntimeError("JSON could not be saved.") from e

    def from_alias(self, alias_name: str) -> Tuple[str, str]:
        """
        Get the command name the given `alias_name` refers to.
        Returns a two-member tuple containing the command name and any args for
        the command alias in the case of complex aliases.
        """
        cmd_name, cmd_args = self.aliases.get(alias_name, ("", ""))

        # If no alias at all, return nothing.
        if not cmd_name:
            return ("", "")

        return (cmd_name, cmd_args)

    def for_command(self, cmd_name: str) -> List[Tuple[str, str]]:
        """
        Get the aliases registered for a given command.
        Returns a list of two-member tuples containing the alias name, and any arguments.
        """
        if cmd_name in self.cmd_aliases:
            return self.cmd_aliases[cmd_name]
        return []

    def exists(self, alias_name: str) -> bool:
        """Test if the given alias exists."""
        if alias_name in ["--comment", "--comments"]:
            return True
        return alias_name in self.aliases

    def make_alias(self, alias_name: str, cmd_name: str, cmd_args: str = "") -> None:
        """
        Add or update an alias with the given command and args.
        """
        ct = (cmd_name, cmd_args)
        cmd_seed = " ".join(list(ct)).strip()
        self.aliases[alias_name] = ct
        if cmd_seed in self.aliases_seed:
            self.aliases_seed[cmd_seed].append(alias_name)
        else:
            self.aliases_seed[cmd_seed] = [alias_name]
        self.cmd_aliases[cmd_name].append((alias_name, cmd_args))

    def remove_alias(self, alias_name: str) -> None:
        """
        Remove an alias if it exists. Not saved to disk.
        """
        if alias_name not in self.aliases:
            return

        # remove from command reverse lookup.
        cmd, args = self.aliases[alias_name]
        cmd_alias = (alias_name, args)
        if cmd in self.cmd_aliases:
            if cmd_alias in self.cmd_aliases[cmd]:
                self.cmd_aliases[cmd].remove(cmd_alias)

        # remove from alias seed data.
        if alias_name in self.aliases_seed:
            del self.aliases_seed[alias_name]
        del self.aliases[alias_name]


class AliasesDefault:
    aliases_file: Path = Path(DEFAULT_COMMAND_ALIAS_FILE)
    aliases_seed: RawAliasJSON = {}
    complex_aliases: AliasesDict = {}
import asyncio
import logging
import pathlib
import shutil
import time
from collections import UserList
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from . import write_path
from .constants import (
    APL_FILE_APLCOPY,
    APL_FILE_DEFAULT,
    APL_FILE_HISTORY,
    OLD_BUNDLED_AUTOPLAYLIST_FILE,
    OLD_DEFAULT_AUTOPLAYLIST_FILE,
)
from .exceptions import MusicbotException

if TYPE_CHECKING:
    from .bot import MusicBot

    StrUserList = UserList[str]
else:
    StrUserList = UserList

log = logging.getLogger(__name__)


class AutoPlaylist(StrUserList):
    def __init__(self, filename: pathlib.Path, bot: "MusicBot") -> None:
        super().__init__()

        self._bot: MusicBot = bot
        self._file: pathlib.Path = filename
        self._removed_file = filename.with_name(f"{filename.stem}.removed.log")

        self._update_lock: asyncio.Lock = asyncio.Lock()
        self._file_lock: asyncio.Lock = asyncio.Lock()
        self._is_loaded: bool = False

    @property
    def filename(self) -> str:
        """The base file name of this playlist."""
        return self._file.name

    @property
    def loaded(self) -> bool:
        """
        Returns the load status of this playlist.
        When False, no playlist data will be available.
        """
        return self._is_loaded

    @property
    def rmlog_file(self) -> pathlib.Path:
        """Returns the generated removal log file name."""
        return self._removed_file

    def create_file(self) -> None:
        """Creates the playlist file if it does not exist."""
        if not self._file.is_file():
            self._file.touch(exist_ok=True)

    async def load(self, force: bool = False) -> None:
        """
        Loads the playlist file if it has not been loaded.
        """
        # ignore loaded lists unless forced.
        if (self._is_loaded or self._file_lock.locked()) and not force:
            return

        # Load the actual playlist file.
        async with self._file_lock:
            try:
                self.data = self._read_playlist()
            except OSError:
                log.warning("Error loading auto playlist file:  %s", self._file)
                self.data = []
                self._is_loaded = False
                return
            self._is_loaded = True

    def _read_playlist(self) -> List[str]:
        """
        Read and parse the playlist file for track entries.
        """
        # Comments in apl files are only handled based on start-of-line.
        # Inline comments are not supported due to supporting non-URL entries.
        comment_char = "#"

        # Read in the file and add non-comments to the playlist.
        playlist: List[str] = []
        with open(self._file, "r", encoding="utf8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(comment_char):
                    continue
                playlist.append(line)
        return playlist

    async def clear_all_tracks(self, log_msg: str) -> None:
        """
        Remove all tracks from the current playlist.
        Functions much like remove_track but does all the I/O stuff in bulk.

        :param: log_msg:  A reason for clearing, usually states the user.
        """
        async with self._update_lock:
            all_tracks = list(self.data)
            song_subject = "[Removed all tracks]"

            for track in all_tracks:
                self.data.remove(track)

            if not self._removed_file.is_file():
                self._removed_file.touch(exist_ok=True)

            try:
                with open(self._removed_file, "a", encoding="utf8") as f:
                    ctime = time.ctime()
                    # add 10 spaces to line up with # Reason:
                    e_str = log_msg.replace("\n", "\n#" + " " * 10)
                    sep = "#" * 32
                    f.write(
                        f"# Entry removed {ctime}\n"
                        f"# Track:  {song_subject}\n"
                        f"# Reason: {e_str}\n"
                        f"\n{sep}\n\n"
                    )
            except (OSError, PermissionError, FileNotFoundError, IsADirectoryError):
                log.exception(
                    "Could not log information about the playlist URL removal."
                )

            log.info("Updating playlist file...")

            def _filter_replace(line: str, url: str) -> str:
                target = line.strip()
                if target == url:
                    return f"# Removed # {url}"
                return line

            # read the original file in and update lines with the URL.
            # this is done to preserve the comments and formatting.
            try:
                data = self._file.read_text(encoding="utf8").split("\n")
                last_track = len(all_tracks) - 1
                self._bot.filecache.cachemap_defer_write = True
                for idx, track in enumerate(all_tracks):
                    data = [_filter_replace(x, track) for x in data]
                    if idx == last_track:
                        self._bot.filecache.cachemap_defer_write = False
                    self._bot.filecache.remove_autoplay_cachemap_entry_by_url(track)

                text = "\n".join(data)
                self._file.write_text(text, encoding="utf8")
            except (OSError, PermissionError, FileNotFoundError):
                log.exception("Failed to save playlist file:  %s", self._file)

    async def remove_track(
        self,
        song_subject: str,
        *,
        ex: Optional[Exception] = None,
        delete_from_ap: bool = False,
    ) -> None:
        """
        Handle clearing the given `song_subject` from the autoplaylist queue,
        and optionally from the configured autoplaylist file.

        :param: ex:  an exception that is given as the reason for removal.
        :param: delete_from_ap:  should the configured list file be updated?
        """
        if song_subject not in self.data:
            return

        async with self._update_lock:
            self.data.remove(song_subject)
            if ex and not isinstance(ex, UserWarning):
                log.info(
                    "Removing unplayable song from playlist, %(playlist)s: %(track)s",
                    {"playlist": self._file.name, "track": song_subject},
                )
            else:
                log.info(
                    "Removing song from playlist, %(playlist)s: %(track)s",
                    {"playlist": self._file.name, "track": song_subject},
                )

            if not self._removed_file.is_file():
                self._removed_file.touch(exist_ok=True)

            try:
                with open(self._removed_file, "a", encoding="utf8") as f:
                    ctime = time.ctime()
                    if isinstance(ex, MusicbotException):
                        error = ex.message % ex.fmt_args
                    else:
                        error = str(ex)
                    # add 10 spaces to line up with # Reason:
                    e_str = error.replace("\n", "\n#" + " " * 10)
                    sep = "#" * 32
                    f.write(
                        f"# Entry removed {ctime}\n"
                        f"# Track:  {song_subject}\n"
                        f"# Reason: {e_str}\n"
                        f"\n{sep}\n\n"
                    )
            except (OSError, PermissionError, FileNotFoundError, IsADirectoryError):
                log.exception(
                    "Could not log information about the playlist URL removal."
                )

            if delete_from_ap:
                log.info("Updating playlist file...")

                def _filter_replace(line: str, url: str) -> str:
                    target = line.strip()
                    if target == url:
                        return f"# Removed # {url}"
                    return line

                # read the original file in and update lines with the URL.
                # this is done to preserve the comments and formatting.
                try:
                    data = self._file.read_text(encoding="utf8").split("\n")
                    data = [_filter_replace(x, song_subject) for x in data]
                    text = "\n".join(data)
                    self._file.write_text(text, encoding="utf8")
                except (OSError, PermissionError, FileNotFoundError):
                    log.exception("Failed to save playlist file:  %s", self._file)
                self._bot.filecache.remove_autoplay_cachemap_entry_by_url(song_subject)

    async def add_track(self, song_subject: str) -> None:
        """
        Add the given `song_subject` to the auto playlist file and in-memory
        list.  Does not update the player's current autoplaylist queue.
        """
        if song_subject in self.data:
            log.debug("URL already in playlist %s, ignoring", self._file.name)
            return

        async with self._update_lock:
            # Note, this does not update the player's copy of the list.
            self.data.append(song_subject)
            log.info(
                "Adding new URL to playlist, %(playlist)s: %(track)s",
                {"playlist": self._file.name, "track": song_subject},
            )

            try:
                # make sure the file exists.
                if not self._file.is_file():
                    self._file.touch(exist_ok=True)

                # append to the file to preserve its formatting.
                with open(self._file, "r+", encoding="utf8") as fh:
                    lines = fh.readlines()
                    if not lines:
                        lines.append("# MusicBot Auto Playlist\n")
                    if lines[-1].endswith("\n"):
                        lines.append(f"{song_subject}\n")
                    else:
                        lines.append(f"\n{song_subject}\n")
                    fh.seek(0)
                    fh.writelines(lines)
            except (OSError, PermissionError, FileNotFoundError):
                log.exception("Failed to save playlist file:  %s", self._file)


class AutoPlaylistManager:
    """Manager class that facilitates multiple playlists."""

    def __init__(self, bot: "MusicBot") -> None:
        """
        Initialize the manager, checking the file system for usable playlists.
        """
        self._bot: MusicBot = bot
        self._apl_dir: pathlib.Path = bot.config.auto_playlist_dir
        self._apl_file_default = self._apl_dir.joinpath(APL_FILE_DEFAULT)
        self._apl_file_history = self._apl_dir.joinpath(APL_FILE_HISTORY)
        self._apl_file_usercopy = self._apl_dir.joinpath(APL_FILE_APLCOPY)

        self._playlists: Dict[str, AutoPlaylist] = {}

        self.setup_autoplaylist()

    def setup_autoplaylist(self) -> None:
        """
        Ensure directories for auto playlists are available and that historic
        playlist files are copied.
        """
        if not self._apl_dir.is_dir():
            self._apl_dir.mkdir(parents=True, exist_ok=True)

        # Files from previous versions of MusicBot
        old_usercopy = write_path(OLD_DEFAULT_AUTOPLAYLIST_FILE)
        old_bundle = write_path(OLD_BUNDLED_AUTOPLAYLIST_FILE)

        # Copy or rename the old auto-playlist files if new files don't exist yet.
        if old_usercopy.is_file() and not self._apl_file_usercopy.is_file():
            # rename the old autoplaylist.txt into the new playlist directory.
            old_usercopy.rename(self._apl_file_usercopy)
        if old_bundle.is_file() and not self._apl_file_default.is_file():
            # copy the bundled playlist into the default, shared playlist.
            shutil.copy(old_bundle, self._apl_file_default)

        if (
            not self._apl_file_history.is_file()
            and self._bot.config.enable_queue_history_global
        ):
            self._apl_file_history.touch(exist_ok=True)

        self.discover_playlists()

    @property
    def _default_pl(self) -> AutoPlaylist:
        """Returns the default playlist, even if the file is deleted."""
        if self._apl_file_default.stem in self._playlists:
            return self._playlists[self._apl_file_default.stem]

        self._playlists[self._apl_file_default.stem] = AutoPlaylist(
            filename=self._apl_file_default,
            bot=self._bot,
        )
        return self._playlists[self._apl_file_default.stem]

    @property
    def _usercopy_pl(self) -> Optional[AutoPlaylist]:
        """Returns the copied autoplaylist.txt playlist if it exists."""
        # return mapped copy if possible.
        if self._apl_file_usercopy.stem in self._playlists:
            return self._playlists[self._apl_file_usercopy.stem]

        # if no mapped copy, check if file exists and map it.
        if self._apl_file_usercopy.is_file():
            self._playlists[self._apl_file_usercopy.stem] = AutoPlaylist(
                filename=self._apl_file_usercopy,
                bot=self._bot,
            )

        return self._playlists.get(self._apl_file_usercopy.stem, None)

    @property
    def global_history(self) -> AutoPlaylist:
        """Returns the MusicBot global history file."""
        if self._apl_file_history.stem in self._playlists:
            return self._playlists[self._apl_file_history.stem]

        self._playlists[self._apl_file_history.stem] = AutoPlaylist(
            filename=self._apl_file_history,
            bot=self._bot,
        )
        return self._playlists[self._apl_file_history.stem]

    @property
    def playlist_names(self) -> List[str]:
        """Returns all discovered playlist names."""
        return list(self._playlists.keys())

    @property
    def loaded_playlists(self) -> List[AutoPlaylist]:
        """Returns all loaded AutoPlaylist objects."""
        return [pl for pl in self._playlists.values() if pl.loaded]

    @property
    def loaded_tracks(self) -> List[str]:
        """
        Contains a list of all unique playlist entries, from each loaded playlist.
        """
        tracks: Set[str] = set()
        for pl in self._playlists.values():
            if pl.loaded:
                tracks = tracks.union(set(pl))
        return list(tracks)

    def discover_playlists(self) -> None:
        """
        Look for available playlist files but do not load them into memory yet.
        This method makes playlists available for display or selection.
        """
        for pfile in self._apl_dir.iterdir():
            # only process .txt files
            if pfile.suffix.lower() == ".txt":
                # ignore already discovered playlists.
                if pfile.stem in self._playlists:
                    continue

                pl = AutoPlaylist(pfile, self._bot)
                self._playlists[pfile.stem] = pl

    def get_default(self) -> AutoPlaylist:
        """
        Gets the appropriate default playlist based on which files exist.
        """
        # If the old autoplaylist.txt was copied, use it.
        if self._usercopy_pl is not None:
            return self._usercopy_pl
        return self._default_pl

    def get_playlist(self, filename: str) -> AutoPlaylist:
        """Get or create a playlist with the given filename."""
        # using pathlib .name here prevents directory traversal attack.
        pl_file = self._apl_dir.joinpath(pathlib.Path(filename).name)

        # Return the existing instance if we have one.
        if pl_file.stem in self._playlists:
            return self._playlists[pl_file.stem]

        # otherwise, make a new instance with this filename
        self._playlists[pl_file.stem] = AutoPlaylist(pl_file, self._bot)
        return self._playlists[pl_file.stem]

    def playlist_exists(self, filename: str) -> bool:
        """Check for the existence of the given playlist file."""
        # using pathlib .name prevents directory traversal attack.
        return self._apl_dir.joinpath(pathlib.Path(filename).name).is_file()
import asyncio
import inspect
import json
import logging
import math
import os
import pathlib
import random
import re
import shutil
import signal
import socket
import ssl
import sys
import time
import traceback
import uuid
from collections import defaultdict
from io import BytesIO, StringIO
from typing import TYPE_CHECKING, Any, DefaultDict, Dict, List, Optional, Set, Union

import aiohttp
import certifi  # type: ignore[import-untyped, unused-ignore]
import discord
import yt_dlp as youtube_dl  # type: ignore[import-untyped]

from . import downloader, exceptions, write_path
from .aliases import Aliases, AliasesDefault
from .autoplaylist import AutoPlaylistManager
from .config import Config, ConfigDefaults
from .constants import (
    DATA_FILE_SERVERS,
    DATA_GUILD_FILE_CUR_SONG,
    DATA_GUILD_FILE_QUEUE,
    DEFAULT_BOT_NAME,
    DEFAULT_I18N_DIR,
    DEFAULT_I18N_LANG,
    DEFAULT_OWNER_GROUP_NAME,
    DEFAULT_PERMS_GROUP_NAME,
    DEFAULT_PING_HTTP_URI,
    DEFAULT_PING_SLEEP,
    DEFAULT_PING_TARGET,
    DEFAULT_PING_TIMEOUT,
    DISCORD_MSG_CHAR_LIMIT,
    EMOJI_CHECK_MARK_BUTTON,
    EMOJI_CROSS_MARK_BUTTON,
    EMOJI_IDLE_ICON,
    EMOJI_NEXT_ICON,
    EMOJI_PREV_ICON,
    EMOJI_RESTART_FULL,
    EMOJI_RESTART_SOFT,
    EMOJI_STOP_SIGN,
    EMOJI_UPDATE_ALL,
    EMOJI_UPDATE_GIT,
    EMOJI_UPDATE_PIP,
    EXAMPLE_OPTIONS_FILE,
    EXAMPLE_PERMS_FILE,
    FALLBACK_PING_SLEEP,
    FALLBACK_PING_TIMEOUT,
    MUSICBOT_USER_AGENT_AIOHTTP,
)
from .constants import VERSION as BOTVERSION
from .constants import VOICE_CLIENT_MAX_RETRY_CONNECT, VOICE_CLIENT_RECONNECT_TIMEOUT
from .constructs import ErrorResponse, GuildSpecificData, MusicBotResponse, Response
from .entry import LocalFilePlaylistEntry, StreamPlaylistEntry, URLPlaylistEntry
from .filecache import AudioFileCache
from .i18n import _D, _L, _Dd
from .logs import muffle_discord_console_log, mute_discord_console_log
from .opus_loader import load_opus_lib
from .permissions import PermissionGroup, Permissions, PermissionsDefaults
from .player import MusicPlayer
from .playlist import Playlist
from .spotify import Spotify
from .utils import (
    _func_,
    command_helper,
    count_members_in_voice,
    dev_only,
    format_size_from_bytes,
    format_song_duration,
    format_time_to_seconds,
    is_empty_voice_channel,
    owner_only,
    slugify,
)

# optional imports
try:
    import objgraph  # type: ignore[import-untyped]
except ImportError:
    objgraph = None


if TYPE_CHECKING:
    from collections.abc import Coroutine
    from contextvars import Context as CtxVars

    AsyncTask = asyncio.Task[Any]
else:
    AsyncTask = asyncio.Task

# Type aliases
ExitSignals = Union[None, exceptions.RestartSignal, exceptions.TerminateSignal]
# Channels that MusicBot Can message.
MessageableChannel = Union[
    discord.VoiceChannel,
    discord.StageChannel,
    discord.TextChannel,
    discord.Thread,
    discord.DMChannel,
    discord.GroupChannel,
    discord.PartialMessageable,
]
GuildMessageableChannels = Union[
    discord.TextChannel,
    discord.Thread,
    discord.VoiceChannel,
    discord.StageChannel,
]
# Voice Channels that MusicBot Can connect to.
VoiceableChannel = Union[
    discord.VoiceChannel,
    discord.StageChannel,
]
MessageAuthor = Union[
    discord.User,
    discord.Member,
]
UserMentions = List[Union[discord.Member, discord.User]]
EntryTypes = Union[URLPlaylistEntry, StreamPlaylistEntry, LocalFilePlaylistEntry]
CommandResponse = Union[None, MusicBotResponse, Response, ErrorResponse]

log = logging.getLogger(__name__)

# Set up discord permissions needed by the bot. Used in auth/invite links.
# We could use the bitmask to save lines, but this documents which perms are needed.
# Bitmask:  4365610048
discord_bot_perms = discord.Permissions()
discord_bot_perms.change_nickname = True
discord_bot_perms.view_channel = True
discord_bot_perms.send_messages = True
discord_bot_perms.manage_messages = True
discord_bot_perms.embed_links = True
discord_bot_perms.attach_files = True
discord_bot_perms.read_message_history = True
discord_bot_perms.use_external_emojis = True
discord_bot_perms.add_reactions = True
discord_bot_perms.connect = True
discord_bot_perms.speak = True
discord_bot_perms.request_to_speak = True


# TODO:  add support for local file playback via indexed data.
#  --  Using tinytag to extract meta data from files and index it.


class MusicBot(discord.Client):
    def __init__(
        self,
        config_file: Optional[pathlib.Path] = None,
        perms_file: Optional[pathlib.Path] = None,
        aliases_file: Optional[pathlib.Path] = None,
        use_certifi: bool = False,
    ) -> None:
        log.info("Initializing MusicBot %s", BOTVERSION)
        load_opus_lib()

        if config_file is None:
            self._config_file = ConfigDefaults.options_file
        else:
            self._config_file = config_file

        if perms_file is None:
            self._perms_file = PermissionsDefaults.perms_file
        else:
            self._perms_file = perms_file

        if aliases_file is None:
            aliases_file = AliasesDefault.aliases_file

        self.use_certifi: bool = use_certifi
        self.exit_signal: ExitSignals = None
        self._init_time: float = time.time()
        self._os_signal: Optional[signal.Signals] = None
        self._ping_peer_addr: str = ""
        self._ping_use_http: bool = False
        self.network_outage: bool = False
        self.on_ready_count: int = 0
        self.init_ok: bool = False
        self.logout_called: bool = False
        self.cached_app_info: Optional[discord.AppInfo] = None
        self.last_status: Optional[discord.BaseActivity] = None
        self.players: Dict[int, MusicPlayer] = {}
        self.task_pool: Set[AsyncTask] = set()

        try:
            self.config = Config(self._config_file)
        except exceptions.RetryConfigException:
            self.config = Config(self._config_file)

        self.permissions = Permissions(self._perms_file)
        # Set the owner ID in case it wasn't auto...
        self.permissions.set_owner_id(self.config.owner_id)

        if self.config.usealias:
            # get a list of natural command names.
            nat_cmds = [
                x.replace("cmd_", "") for x in dir(self) if x.startswith("cmd_")
            ]
            # load the aliases file.
            self.aliases = Aliases(aliases_file, nat_cmds)

        self.playlist_mgr = AutoPlaylistManager(self)

        self.aiolocks: DefaultDict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.filecache = AudioFileCache(self)
        self.downloader = downloader.Downloader(self)

        # Factory function for server specific data objects.
        def server_factory() -> GuildSpecificData:
            return GuildSpecificData(self)

        # defaultdict lets us on-demand create GuildSpecificData.
        self.server_data: DefaultDict[int, GuildSpecificData] = defaultdict(
            server_factory
        )

        self.spotify: Optional[Spotify] = None
        self.session: Optional[aiohttp.ClientSession] = None

        intents = discord.Intents.all()
        intents.typing = False
        intents.presences = False
        super().__init__(intents=intents)

    def create_task(
        self,
        coro: "Coroutine[Any, Any, Any]",
        *,
        name: Optional[str] = None,
        ctx: Optional["CtxVars"] = None,
    ) -> None:
        """
        Same as asyncio.create_task() but manages the task reference.
        This prevents garbage collection of tasks until they are finished.
        """
        if not self.loop:
            log.error("Loop is closed, cannot create task for: %r", coro)
            return

        # context was not added until python 3.11
        if sys.version_info >= (3, 11):
            t = self.loop.create_task(coro, name=name, context=ctx)
        else:  # assume 3.8 +
            t = self.loop.create_task(coro, name=name)
        self.task_pool.add(t)

        def discard_task(task: AsyncTask) -> None:
            """Clean up the spawned task and handle its exceptions."""
            ex = task.exception()
            if ex:
                if log.getEffectiveLevel() <= logging.DEBUG:
                    log.exception(
                        "Unhandled exception for task:  %r", task, exc_info=ex
                    )
                else:
                    log.error(
                        "Unhandled exception for task:  %(task)r  --  %(raw_error)s",
                        {"task": task, "raw_error": str(ex)},
                    )

            self.task_pool.discard(task)

        t.add_done_callback(discard_task)

    async def setup_hook(self) -> None:
        """async init phase that is called by d.py before login."""
        if self.config.enable_queue_history_global:
            await self.playlist_mgr.global_history.load()

        # TODO: testing is needed to see if this would be required.
        # See also:  https://github.com/aio-libs/aiohttp/discussions/6044
        # aiohttp version must be at least 3.8.0 for the following to potentially work.
        # Python 3.11+ might also be a requirement if CPython does not support start_tls.
        # setattr(asyncio.sslproto._SSLProtocolTransport, "_start_tls_compatible", True)

        self.http.user_agent = MUSICBOT_USER_AGENT_AIOHTTP
        if self.use_certifi:
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            tcp_connector = aiohttp.TCPConnector(ssl_context=ssl_ctx)

            # Patches discord.py HTTPClient.
            self.http.connector = tcp_connector

            self.session = aiohttp.ClientSession(
                headers={"User-Agent": self.http.user_agent},
                connector=tcp_connector,
            )
        else:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": self.http.user_agent}
            )

        if self.config.spotify_enabled:
            try:
                self.spotify = Spotify(
                    self.config.spotify_clientid,
                    self.config.spotify_clientsecret,
                    aiosession=self.session,
                    loop=self.loop,
                )
                if not await self.spotify.has_token():
                    log.warning("Spotify did not provide us with a token. Disabling.")
                    self.config.spotify_enabled = False
                else:
                    log.info(
                        "Authenticated with Spotify successfully using client ID and secret."
                    )
            except exceptions.SpotifyError as e:
                log.warning(
                    "Could not start Spotify client. Is your client ID and secret correct? Details: %s. Continuing anyway in 5 seconds...",
                    e.message % e.fmt_args,
                )
                self.config.spotify_enabled = False
                time.sleep(5)  # make sure they see the problem
        else:
            try:
                log.warning(
                    "The config did not have Spotify app credentials, attempting to use guest mode."
                )
                self.spotify = Spotify(
                    None, None, aiosession=self.session, loop=self.loop
                )
                if not await self.spotify.has_token():
                    log.warning("Spotify did not provide us with a token. Disabling.")
                    self.config.spotify_enabled = False
                else:
                    log.info(
                        "Authenticated with Spotify successfully using guest mode."
                    )
                    self.config.spotify_enabled = True
            except exceptions.SpotifyError as e:
                log.warning(
                    "Could not start Spotify client using guest mode. Details: %s.",
                    e.message % e.fmt_args,
                )
                self.config.spotify_enabled = False

        # trigger yt tv oauth2 authorization.
        if self.config.ytdlp_use_oauth2 and self.config.ytdlp_oauth2_url:
            log.warning(
                "Experimental Yt-dlp OAuth2 plugin is enabled. This might break at any point!"
            )
            # could probably do this with items from an auto-playlist but meh.
            await self.downloader.extract_info(
                self.config.ytdlp_oauth2_url, download=False, process=True
            )

        log.info("Initialized, now connecting to discord.")
        # this creates an output similar to a progress indicator.
        muffle_discord_console_log()
        self.create_task(self._test_network(), name="MB_PingTest")

    async def _test_network(self) -> None:
        """
        A self looping method that tests network connectivity.
        This will call to the systems ping command and use its return status.
        """
        if not self.config.enable_network_checker:
            log.debug("Network ping test is disabled via config.")
            return

        if self.logout_called:
            log.noise("Network ping test is closing down.")  # type: ignore[attr-defined]
            return

        # Resolve the given target to speed up pings.
        ping_target = self._ping_peer_addr
        if not self._ping_peer_addr:
            try:
                ai = socket.getaddrinfo(DEFAULT_PING_TARGET, 80)
                self._ping_peer_addr = ai[0][4][0]
                ping_target = self._ping_peer_addr
            except OSError:
                log.warning("Could not resolve ping target.")
                ping_target = DEFAULT_PING_TARGET

        # Make a ping test using sys ping command or http request.
        if self._ping_use_http:
            ping_status = await self._test_network_via_http(ping_target)
        else:
            ping_status = await self._test_network_via_ping(ping_target)
            if self._ping_use_http:
                ping_status = await self._test_network_via_http(ping_target)

        # Ping success, network up.
        if ping_status == 0:
            if self.network_outage:
                self.on_network_up()
            self.network_outage = False

        # Ping failed, network down.
        else:
            if not self.network_outage:
                self.on_network_down()
            self.network_outage = True

        # Sleep before next ping.
        try:
            if not self._ping_use_http:
                await asyncio.sleep(DEFAULT_PING_SLEEP)
            else:
                await asyncio.sleep(FALLBACK_PING_SLEEP)
        except asyncio.exceptions.CancelledError:
            log.noise("Network ping test cancelled.")  # type: ignore[attr-defined]
            return

        # set up the next ping task if possible.
        if not self.logout_called:
            self.create_task(self._test_network(), name="MB_PingTest")

    async def _test_network_via_http(self, ping_target: str) -> int:
        """
        This method is used as a fall-back if system ping commands are not available.
        It will make use of current aiohttp session to make a HEAD request for the
        given `ping_target` and a file defined by DEFAULT_PING_HTTP_URI.
        """
        if not self.session:
            log.warning("Network testing via HTTP does not have a session to borrow.")
            # As we cannot test it, assume network is up.
            return 0

        try:
            ping_host = f"http://{ping_target}{DEFAULT_PING_HTTP_URI}"
            async with self.session.head(
                ping_host,
                timeout=FALLBACK_PING_TIMEOUT,  # type: ignore[arg-type,unused-ignore]
            ):
                return 0
        except (aiohttp.ClientError, asyncio.exceptions.TimeoutError, OSError):
            return 1

    async def _test_network_via_ping(self, ping_target: str) -> int:
        """
        This method constructs a ping command to use as a system call.
        If ping cannot be found or is not permitted, the fall-back flag
        will be set by this function, and subsequent ping tests will use
        HTTP ping testing method instead.
        """
        # Make a ping call based on OS.
        if not hasattr(self, "_mb_ping_exe_path"):
            ping_path = shutil.which("ping")
            if not ping_path:
                log.warning("Could not locate `ping` executable in your environment.")
                ping_path = "ping"
            setattr(self, "_mb_ping_exe_path", ping_path)
        else:
            ping_path = getattr(self, "_mb_ping_exe_path", "ping")

        ping_cmd: List[str] = []
        if os.name == "nt":
            # Windows ping -w uses milliseconds.
            t = 1000 * DEFAULT_PING_TIMEOUT
            ping_cmd = [ping_path, "-n", "1", "-w", str(t), ping_target]
        else:
            t = DEFAULT_PING_TIMEOUT
            ping_cmd = [ping_path, "-c", "1", "-w", str(t), ping_target]

        # execute the ping command.
        try:
            p = await asyncio.create_subprocess_exec(
                ping_cmd[0],
                *ping_cmd[1:],
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            ping_status = await p.wait()
        except FileNotFoundError:
            log.error(
                "MusicBot could not locate a `ping` command path.  Will attempt to use HTTP ping instead."
                "\nMusicBot tried the following command:   %s"
                "\nYou should enable ping in your system or container environment for best results."
                "\nAlternatively disable network checking via config.",
                " ".join(ping_cmd),
            )
            self._ping_use_http = True
            return 1
        except PermissionError:
            log.error(
                "MusicBot was denied permission to execute the `ping` command.  Will attempt to use HTTP ping instead."
                "\nMusicBot tried the following command:   %s"
                "\nYou should enable ping in your system or container environment for best results."
                "\nAlternatively disable network checking via config.",
                " ".join(ping_cmd),
            )
            self._ping_use_http = True
            return 1
        except OSError:
            log.error(
                "Your environment may not allow the `ping` system command.  Will attempt to use HTTP ping instead."
                "\nMusicBot tried the following command:   %s"
                "\nYou should enable ping in your system or container environment for best results."
                "\nAlternatively disable network checking via config.",
                " ".join(ping_cmd),
                exc_info=self.config.debug_mode,
            )
            self._ping_use_http = True
            return 1
        return ping_status

    def on_network_up(self) -> None:
        """
        Event called by MusicBot when it detects network returned from outage.
        """
        log.info("MusicBot detected network is available again.")
        for gid, player in self.players.items():
            if player.is_paused and not player.paused_auto:
                if not player.voice_client.is_connected():
                    log.warning(
                        "VoiceClient is not connected, waiting to resume MusicPlayer..."
                    )
                    continue
                log.info(
                    "Resuming playback of player:  (%(guild_id)s) %(player)r",
                    {"guild_id": gid, "player": player},
                )
                player.guild_or_net_unavailable = False
                player.resume()
            player.guild_or_net_unavailable = False

    def on_network_down(self) -> None:
        """
        Event called by MusicBot when it detects network outage.
        """
        log.info("MusicBot detected a network outage.")
        for gid, player in self.players.items():
            if player.is_playing:
                log.info(
                    "Pausing MusicPlayer due to network availability:  (%(guild_id)s) %(player)r",
                    {"guild_id": gid, "player": player},
                )
                player.pause()
            player.guild_or_net_unavailable = True

    def _get_owner_member(
        self, *, server: Optional[discord.Guild] = None, voice: bool = False
    ) -> Optional[discord.Member]:
        """
        Get the discord Member object that has a user ID which matches
        the configured OwnerID.

        :param: server:  The discord Guild in which to expect the member.
        :param: voice:  Require the owner to be in a voice channel.
        """
        owner = discord.utils.find(
            lambda m: m.id == self.config.owner_id and (m.voice if voice else True),
            server.members if server else self.get_all_members(),
        )
        log.noise(  # type: ignore[attr-defined]
            "Looking for owner in guild: %(guild)s (required voice: %(required)s) and got:  %(owner)s",
            {"guild": server, "required": voice, "owner": owner},
        )
        return owner

    async def _auto_join_channels(
        self,
        from_resume: bool = False,
    ) -> None:
        """
        Attempt to join voice channels that have been configured in options.
        Also checks for existing voice sessions and attempts to resume them.
        If self.on_ready_count is 0, it will also run owner auto-summon logic.
        """
        log.info("Checking for channels to auto-join or resume...")
        channel_map: Dict[discord.Guild, VoiceableChannel] = {}

        # Check guilds for a resumable channel, conditionally override with owner summon.
        resuming = False
        for guild in self.guilds:
            auto_join_ch = self.server_data[guild.id].auto_join_channel
            if auto_join_ch:
                channel_map[guild] = auto_join_ch

            if guild.unavailable:
                log.warning(
                    "Guild not available, cannot auto join:  %(id)s/%(name)s",
                    {"id": guild.id, "name": guild.name},
                )
                continue

            # Check for a resumable channel.
            if guild.me.voice and guild.me.voice.channel:
                log.info(
                    "Found resumable voice channel:  %(channel)s  in guild:  %(guild)s",
                    {
                        "channel": guild.me.voice.channel.name,
                        "guild": guild.name,
                    },
                )

                # override an existing auto-join if bot was previously in a different channel.
                if (
                    guild in channel_map
                    and guild.me.voice.channel != channel_map[guild]
                ):
                    log.info(
                        "Will try resuming voice session instead of Auto-Joining channel:  %s",
                        channel_map[guild].name,
                    )
                channel_map[guild] = guild.me.voice.channel
                resuming = True

            # Check for follow-user mode on resume.
            follow_user = self.server_data[guild.id].follow_user
            if from_resume and follow_user:
                if follow_user.voice and follow_user.voice.channel:
                    channel_map[guild] = follow_user.voice.channel

            # Check if we should auto-summon to the owner, but only on startup.
            if self.config.auto_summon and not from_resume:
                owner = self._get_owner_member(server=guild, voice=True)
                if owner and owner.voice and owner.voice.channel:
                    log.info(
                        "Found owner in voice channel:  %s", owner.voice.channel.name
                    )
                    if guild in channel_map:
                        if resuming:
                            log.info(
                                "Ignoring resumable channel, AutoSummon to owner in channel:  %s",
                                owner.voice.channel.name,
                            )
                        else:
                            log.info(
                                "Ignoring Auto-Join channel, AutoSummon to owner in channel:  %s",
                                owner.voice.channel.name,
                            )
                    channel_map[guild] = owner.voice.channel

        for guild, channel in channel_map.items():

            if (
                isinstance(guild.voice_client, discord.VoiceClient)
                and guild.voice_client.is_connected()
            ):
                log.info(
                    "Already connected to channel:  %(channel)s  in guild:  %(guild)s",
                    {"channel": guild.voice_client.channel.name, "guild": guild.name},
                )
                continue

            if channel and isinstance(
                channel, (discord.VoiceChannel, discord.StageChannel)
            ):
                log.info(
                    "Attempting to join channel:  %(channel)s  in guild:  %(guild)s",
                    {"channel": channel.name, "guild": channel.guild},
                )

                player = self.get_player_in(guild)

                if player:
                    log.info("Discarding MusicPlayer and making a new one...")
                    await self.disconnect_voice_client(guild)

                    try:
                        player = await self.get_player(
                            channel,
                            create=True,
                            deserialize=self.config.persistent_queue,
                        )

                        if player.is_stopped and len(player.playlist) > 0:
                            player.play()

                        if self.config.auto_playlist and len(player.playlist) == 0:
                            await self.on_player_finished_playing(player)

                    except (TypeError, exceptions.PermissionsError):
                        continue

                else:
                    log.debug("MusicBot will make a new MusicPlayer now...")
                    try:
                        player = await self.get_player(
                            channel,
                            create=True,
                            deserialize=self.config.persistent_queue,
                        )

                        if player.is_stopped and len(player.playlist) > 0:
                            player.play()

                        if self.config.auto_playlist and len(player.playlist) == 0:
                            await self.on_player_finished_playing(player)

                    except (TypeError, exceptions.PermissionsError):
                        continue

            if channel and not isinstance(
                channel, (discord.VoiceChannel, discord.StageChannel)
            ):
                log.warning(
                    "Not joining %(guild)s/%(channel)s, it isn't a supported voice channel.",
                    {"guild": channel.guild.name, "channel": channel.name},
                )
        log.info("Finished joining configured channels.")

    async def _check_ignore_non_voice(self, msg: discord.Message) -> bool:
        """Check used by on_message to determine if caller is in a VoiceChannel."""
        if msg.guild and msg.guild.me.voice:
            vc = msg.guild.me.voice.channel
        else:
            vc = None

        # Webhooks can't be voice members. discord.User has no .voice attribute.
        if isinstance(msg.author, discord.User):
            raise exceptions.CommandError(
                "Member is not voice-enabled and cannot use this command.",
            )

        # If we've connected to a voice chat and we're in the same voice channel
        if not vc or (msg.author.voice and vc == msg.author.voice.channel):
            return True

        raise exceptions.PermissionsError(
            "You cannot use this command when not in the voice channel.",
        )

    async def generate_invite_link(
        self,
        *,
        permissions: discord.Permissions = discord_bot_perms,
        guild: discord.Guild = discord.utils.MISSING,
    ) -> str:
        """
        Fetch Application Info from discord and generate an OAuth invite
        URL for MusicBot.
        """
        if not self.cached_app_info:
            log.debug("Getting bot Application Info.")
            self.cached_app_info = await self.application_info()

        return discord.utils.oauth_url(
            self.cached_app_info.id, permissions=permissions, guild=guild
        )

    async def get_voice_client(self, channel: VoiceableChannel) -> discord.VoiceClient:
        """
        Use the given `channel` either return an existing VoiceClient or
        create a new VoiceClient by connecting to the `channel` object.

        :raises: TypeError
            If `channel` is not a discord.VoiceChannel or discord.StageChannel

        :raises: musicbot.exceptions.PermissionsError
            If MusicBot does not have permissions required to join or speak in the `channel`.
        """
        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            raise TypeError("[BUG] Channel passed must be a voice channel")

        # Check if MusicBot has required permissions to join in channel.
        chperms = channel.permissions_for(channel.guild.me)
        if not chperms.connect:
            log.error(
                "MusicBot does not have permission to Connect in channel:  %s",
                channel.name,
            )
            raise exceptions.PermissionsError(
                "MusicBot does not have permission to Connect in channel:  `%(name)s`",
                fmt_args={"name": channel.name},
            )
        if not chperms.speak:
            log.error(
                "MusicBot does not have permission to Speak in channel:  %s",
                channel.name,
            )
            raise exceptions.PermissionsError(
                "MusicBot does not have permission to Speak in channel:  `%(name)s`",
                fmt_args={"name": channel.name},
            )

        # check for and return bots VoiceClient if we already have one.
        vc = channel.guild.voice_client
        if vc and isinstance(vc, (discord.VoiceClient, discord.StageChannel)):
            # make sure it is usable
            if vc.is_connected():
                log.voicedebug(  # type: ignore[attr-defined]
                    "Reusing bots VoiceClient from guild:  %s", channel.guild
                )
                return vc
            # or otherwise we kill it and start fresh.
            log.voicedebug(  # type: ignore[attr-defined]
                "Forcing disconnect on stale VoiceClient in guild:  %s", channel.guild
            )
            try:
                await vc.disconnect()
            except (asyncio.exceptions.CancelledError, asyncio.exceptions.TimeoutError):
                if self.config.debug_mode:
                    log.warning("Disconnect failed or was cancelled?")

        # Otherwise we need to connect to the given channel.
        max_timeout = VOICE_CLIENT_RECONNECT_TIMEOUT * VOICE_CLIENT_MAX_RETRY_CONNECT
        for attempt in range(1, (VOICE_CLIENT_MAX_RETRY_CONNECT + 1)):
            timeout = attempt * VOICE_CLIENT_RECONNECT_TIMEOUT
            if timeout > max_timeout:
                log.critical(
                    "MusicBot is unable to connect to the channel right now:  %(channel)s",
                    {"channel": channel},
                )
                raise exceptions.CommandError(
                    "MusicBot could not connect to the channel.\n"
                    "Try again later, or restart the bot if this continues."
                )

            try:
                client: discord.VoiceClient = await channel.connect(
                    timeout=timeout,
                    reconnect=True,
                    self_deaf=self.config.self_deafen,
                )
                log.voicedebug(  # type: ignore[attr-defined]
                    "MusicBot has a VoiceClient now..."
                )
                break
            except asyncio.exceptions.TimeoutError:
                log.warning(
                    "Retrying connection after a timeout error (%(attempt)s) while trying to connect to:  %(channel)s",
                    {"attempt": attempt, "channel": channel},
                )
            except asyncio.exceptions.CancelledError as e:
                log.exception(
                    "MusicBot VoiceClient connection attempt was cancelled. No retry."
                )
                raise exceptions.CommandError(
                    "MusicBot connection to voice was cancelled. This is odd. Maybe restart?"
                ) from e

        # request speaker automatically in stage channels.
        if isinstance(channel, discord.StageChannel):
            try:
                log.info("MusicBot is requesting to speak in channel: %s", channel.name)
                # this has the same effect as edit(suppress=False)
                await channel.guild.me.request_to_speak()
            except discord.Forbidden as e:
                raise exceptions.PermissionsError(
                    "MusicBot does not have permission to speak."
                ) from e
            except (discord.HTTPException, discord.ClientException) as e:
                raise exceptions.MusicbotException(
                    "MusicBot could not request to speak."
                ) from e

        return client

    async def disconnect_voice_client(self, guild: discord.Guild) -> None:
        """
        Check for a MusicPlayer in the given `guild` and close it's VoiceClient
        gracefully then remove the MusicPlayer instance and reset any timers on
        the guild for player/channel inactivity.
        """

        if guild.id in self.players:
            log.info("Disconnecting a MusicPlayer in guild:  %s", guild)
            player = self.players.pop(guild.id)

            await self.reset_player_inactivity(player)

            # reset channel inactivity.
            if self.config.leave_inactive_channel:
                event = self.server_data[guild.id].get_event("inactive_vc_timer")
                if event.is_active() and not event.is_set():
                    event.set()

            if player.voice_client:
                log.debug("Disconnecting VoiceClient before we kill the MusicPlayer.")
                try:
                    await player.voice_client.disconnect()
                except (
                    asyncio.exceptions.CancelledError,
                    asyncio.exceptions.TimeoutError,
                ):
                    if self.config.debug_mode:
                        log.warning("The disconnect failed or was cancelled.")

            # ensure the player is dead and gone.
            player.kill()
            del player

        # Double check for voice objects.
        for vc in self.voice_clients:
            if not isinstance(vc, discord.VoiceClient):
                log.debug(
                    "MusicBot has a VoiceProtocol that is not a VoiceClient. Disconnecting anyway..."
                )
                try:
                    await vc.disconnect(force=True)
                except (
                    asyncio.exceptions.CancelledError,
                    asyncio.exceptions.TimeoutError,
                ):
                    if self.config.debug_mode:
                        log.warning("The disconnect failed or was cancelled.")
                continue

            if vc.guild and vc.guild == guild:
                log.debug("Disconnecting a rogue VoiceClient in guild:  %s", guild)
                try:
                    await vc.disconnect()
                except (
                    asyncio.exceptions.CancelledError,
                    asyncio.exceptions.TimeoutError,
                ):
                    if self.config.debug_mode:
                        log.warning("The disconnect failed or was cancelled.")

        await self.update_now_playing_status()

    async def disconnect_all_voice_clients(self) -> None:
        """
        Loop over all references that may have a VoiceClient and ensure they are
        closed and disposed of in the case of MusicPlayer.
        """
        # Disconnect from all guilds.
        for guild in self.guilds:
            await self.disconnect_voice_client(guild)

        # Double check for detached voice clients.
        for vc in self.voice_clients:
            if isinstance(vc, discord.VoiceClient):
                log.warning("Disconnecting a non-guild VoiceClient...")
                try:
                    await vc.disconnect()
                except (
                    asyncio.exceptions.CancelledError,
                    asyncio.exceptions.TimeoutError,
                ):
                    log.warning("The disconnect failed or was cancelled.")
            else:
                log.warning(
                    "MusicBot.voice_clients list contains a non-VoiceClient object?\n"
                    "The object is actually of type:  %s",
                    type(vc),
                )

        # Triple check we don't have rogue players.  This would be a bug.
        player_gids = list(self.players.keys())
        for gid in player_gids:
            player = self.players[gid]
            log.warning(
                "We still have a MusicPlayer ref in guild (%(guild_id)s):  %(player)r",
                {"guild_id": gid, "player": player},
            )
            del self.players[gid]

    def get_player_in(self, guild: discord.Guild) -> Optional[MusicPlayer]:
        """
        Get a MusicPlayer in the given guild, but do not create a new player.
        MusicPlayer returned from this method may not be connected to a voice channel!
        """
        p = self.players.get(guild.id)
        if log.getEffectiveLevel() <= logging.EVERYTHING:  # type: ignore[attr-defined]
            log.voicedebug(  # type: ignore[attr-defined]
                "Guild (%(guild)s) wants a player, optional:  %(player)r",
                {"guild": guild, "player": p},
            )

        if log.getEffectiveLevel() <= logging.VOICEDEBUG:  # type: ignore[attr-defined]
            if p and not p.voice_client:
                log.error(
                    "[BUG] MusicPlayer is missing a VoiceClient somehow.  You should probably restart the bot."
                )
            if p and p.voice_client and not p.voice_client.is_connected():
                # This is normal if the bot is still connecting to voice, or
                # if the player has been pointedly disconnected.
                log.warning("MusicPlayer has a VoiceClient that is not connected.")
                log.noise("MusicPlayer obj:  %r", p)  # type: ignore[attr-defined]
                log.noise("VoiceClient obj:  %r", p.voice_client)  # type: ignore[attr-defined]
        return p

    async def get_player(
        self,
        channel: VoiceableChannel,
        create: bool = False,
        deserialize: bool = False,
    ) -> MusicPlayer:
        """
        Get a MusicPlayer in the given guild, creating or deserializing one if needed.

        :raises:  TypeError
            If given `channel` is not a discord.VoiceChannel or discord.StageChannel
        :raises:  musicbot.exceptions.PermissionsError
            If MusicBot is not permitted to join the given `channel`.
        """
        guild = channel.guild

        log.voicedebug(  # type: ignore[attr-defined]
            "Getting a MusicPlayer for guild:  %(guild)s  In Channel:  %(channel)s  Create: %(create)s  Deserialize:  %(serial)s",
            {
                "guild": guild,
                "channel": channel,
                "create": create,
                "serial": deserialize,
            },
        )

        async with self.aiolocks[_func_() + ":" + str(guild.id)]:
            if deserialize:
                voice_client = await self.get_voice_client(channel)
                player = await self.deserialize_queue(guild, voice_client)

                if player:
                    log.voicedebug(  # type: ignore[attr-defined]
                        "Created player via deserialization for guild %(guild_id)s with %(number)s entries",
                        {"guild_id": guild.id, "number": len(player.playlist)},
                    )
                    # Since deserializing only happens when the bot starts, I should never need to reconnect
                    return self._init_player(player, guild=guild)

            if guild.id not in self.players:
                if not create:
                    raise exceptions.CommandError(
                        "The bot is not in a voice channel.\n"
                        "Use the summon command to bring the bot to your voice channel."
                    )

                voice_client = await self.get_voice_client(channel)

                if isinstance(voice_client, discord.VoiceClient):
                    playlist = Playlist(self)
                    player = MusicPlayer(self, voice_client, playlist)
                    self._init_player(player, guild=guild)
                else:
                    raise exceptions.MusicbotException(
                        "Something is wrong, we didn't get the VoiceClient."
                    )

        return self.players[guild.id]

    def _init_player(
        self, player: MusicPlayer, *, guild: Optional[discord.Guild] = None
    ) -> MusicPlayer:
        """
        Connect a brand-new MusicPlayer instance with the MusicBot event
        handler functions, and store the player reference for reuse.

        :returns: The player with it's event connections.
        """
        player = (
            player.on("play", self.on_player_play)
            .on("resume", self.on_player_resume)
            .on("pause", self.on_player_pause)
            .on("stop", self.on_player_stop)
            .on("finished-playing", self.on_player_finished_playing)
            .on("entry-added", self.on_player_entry_added)
            .on("error", self.on_player_error)
        )

        if guild:
            self.players[guild.id] = player

        return player

    async def on_player_play(self, player: MusicPlayer, entry: EntryTypes) -> None:
        """
        Event called by MusicPlayer when playback of an entry is started.
        """
        log.debug("Running on_player_play")
        ssd_ = self.server_data[player.voice_client.channel.guild.id]
        await self._handle_guild_auto_pause(player)
        await self.reset_player_inactivity(player)
        await self.update_now_playing_status()
        # manage the cache since we may have downloaded something.
        if isinstance(entry, URLPlaylistEntry):
            self.filecache.handle_new_cache_entry(entry)
        player.skip_state.reset()

        await self.serialize_queue(player.voice_client.channel.guild)

        if self.config.write_current_song:
            await self.write_current_song(player.voice_client.channel.guild, entry)

        if entry.channel and entry.author:
            author_perms = self.permissions.for_user(entry.author)

            if (
                entry.author not in player.voice_client.channel.members
                and author_perms.skip_when_absent
            ):
                newmsg = _D(
                    "Skipping next song `%(title)s` as requester `%(user)s` is not in voice!",
                    ssd_,
                ) % {
                    "title": _D(entry.title, ssd_),
                    "author": entry.author.name,
                }

                # handle history playlist updates.
                guild = player.voice_client.guild
                if (
                    self.config.enable_queue_history_global
                    or self.config.enable_queue_history_guilds
                ):
                    self.server_data[guild.id].current_playing_url = ""

                player.skip()
            elif self.config.now_playing_mentions:
                newmsg = _D(
                    "%(mention)s - your song `%(title)s` is now playing in %(channel)s!",
                    ssd_,
                ) % {
                    "mention": entry.author.mention,
                    "title": _D(entry.title, ssd_),
                    "channel": player.voice_client.channel.name,
                }
            else:
                newmsg = _D(
                    "Now playing in %(channel)s: `%(title)s` added by %(author)s!",
                    ssd_,
                ) % {
                    "channel": player.voice_client.channel.name,
                    "title": _D(entry.title, ssd_),
                    "author": entry.author.name,
                }

        else:
            # no author (and channel), it's an auto playlist entry.
            newmsg = _D(
                "Now playing automatically added entry `%(title)s` in %(channel)s!",
                ssd_,
            ) % {
                "title": _D(entry.title, ssd_),
                "channel": player.voice_client.channel.name,
            }

        # handle history playlist updates.
        guild = player.voice_client.guild
        if (
            self.config.enable_queue_history_global
            or self.config.enable_queue_history_guilds
        ) and not entry.from_auto_playlist:
            log.debug(
                "Setting URL history guild %(guild_id)s == %(url)s",
                {"guild_id": guild.id, "url": entry.url},
            )
            self.server_data[guild.id].current_playing_url = entry.url

        last_np_msg = self.server_data[guild.id].last_np_msg
        np_channel: Optional[MessageableChannel] = None
        if newmsg:
            if self.config.dm_nowplaying and entry.author:
                await self.safe_send_message(entry.author, Response(newmsg))
                return

            if self.config.no_nowplaying_auto and entry.from_auto_playlist:
                return

            if self.config.nowplaying_channels:
                for potential_channel_id in self.config.nowplaying_channels:
                    potential_channel = self.get_channel(potential_channel_id)
                    if isinstance(potential_channel, discord.abc.PrivateChannel):
                        continue

                    if not isinstance(potential_channel, discord.abc.Messageable):
                        continue

                    if potential_channel and potential_channel.guild == guild:
                        np_channel = potential_channel
                        break

            if not np_channel and last_np_msg:
                np_channel = last_np_msg.channel

        content = Response("")
        if entry.thumbnail_url:
            content.set_image(url=entry.thumbnail_url)
        else:
            log.warning(
                "No thumbnail set for entry with URL: %s",
                entry.url,
            )

        if self.config.now_playing_mentions:
            content.title = None
            content.add_field(name="\n", value=newmsg, inline=True)
        else:
            content.title = newmsg

        # send it in specified channel
        if not np_channel:
            log.debug("no channel to put now playing message into")
            return

        # Don't send the same now-playing message more than once.
        # This prevents repeated messages when players reconnect.
        last_subject = self.server_data[guild.id].last_played_song_subject
        if (
            last_np_msg is not None
            and player.current_entry is not None
            and last_subject
            and last_subject == player.current_entry.url
        ):
            log.debug("ignored now-playing message as it was already posted.")
            return

        if player.current_entry:
            self.server_data[guild.id].last_played_song_subject = (
                player.current_entry.url
            )

        self.server_data[guild.id].last_np_msg = await self.safe_send_message(
            np_channel,
            content,
        )

        # TODO: Check channel voice state?

    async def on_player_resume(
        self,
        player: MusicPlayer,
        entry: EntryTypes,  # pylint: disable=unused-argument
        **_: Any,
    ) -> None:
        """
        Event called by MusicPlayer when the player is resumed from pause.
        """
        log.debug("Running on_player_resume")
        await self.reset_player_inactivity(player)
        await self.update_now_playing_status()

    async def on_player_pause(
        self,
        player: MusicPlayer,
        entry: EntryTypes,  # pylint: disable=unused-argument
        **_: Any,
    ) -> None:
        """
        Event called by MusicPlayer when the player enters paused state.
        """
        log.debug("Running on_player_pause")
        await self.update_now_playing_status()

        # save current entry progress, if it played "enough" to merit saving.
        if player.session_progress > 1:
            await self.serialize_queue(player.voice_client.channel.guild)

        self.create_task(
            self.handle_player_inactivity(player), name="MB_HandleInactivePlayer"
        )

    async def on_player_stop(self, player: MusicPlayer, **_: Any) -> None:
        """
        Event called by MusicPlayer any time the player is stopped.
        Typically after queue is empty or an error stopped playback.
        """
        log.debug("Running on_player_stop")
        await self.update_now_playing_status()
        self.create_task(
            self.handle_player_inactivity(player), name="MB_HandleInactivePlayer"
        )

    async def on_player_finished_playing(self, player: MusicPlayer, **_: Any) -> None:
        """
        Event called by MusicPlayer when playback has finished without error.
        """
        log.debug("Running on_player_finished_playing")
        if not self.loop or (self.loop and self.loop.is_closed()):
            log.debug("Event loop is closed, nothing else to do here.")
            return

        if self.logout_called:
            log.debug("Logout under way, ignoring this event.")
            return

        # handle history playlist updates.
        guild = player.voice_client.guild
        last_played_url = self.server_data[guild.id].current_playing_url
        if self.config.enable_queue_history_global and last_played_url:
            await self.playlist_mgr.global_history.add_track(last_played_url)

        if self.config.enable_queue_history_guilds and last_played_url:
            history = await self.server_data[guild.id].get_played_history()
            if history is not None:
                await history.add_track(last_played_url)
        self.server_data[guild.id].current_playing_url = ""

        if not player.voice_client.is_connected():
            log.debug(
                "VoiceClient says it is not connected, nothing else we can do here."
            )
            return

        if self.config.leave_after_queue_empty:
            guild = player.voice_client.guild
            if len(player.playlist.entries) == 0:
                log.info("Player finished and queue is empty, leaving voice channel...")
                await self.disconnect_voice_client(guild)

        # delete last_np_msg somewhere if we have cached it
        if self.config.delete_nowplaying:
            guild = player.voice_client.guild
            last_np_msg = self.server_data[guild.id].last_np_msg
            if last_np_msg:
                await self.safe_delete_message(last_np_msg)

        # avoid downloading the next entries if the user is absent and we are configured to skip.
        notice_sent = False  # set a flag to avoid message spam.
        while len(player.playlist):
            log.everything(  # type: ignore[attr-defined]
                "Looping over queue to expunge songs with missing author..."
            )

            if not self.loop or (self.loop and self.loop.is_closed()):
                log.debug("Event loop is closed, nothing else to do here.")
                return

            if self.logout_called:
                log.debug("Logout under way, ignoring this event.")
                return

            next_entry = player.playlist.peek()

            if not next_entry:
                break

            channel = next_entry.channel
            author = next_entry.author

            if not channel or not author:
                break

            author_perms = self.permissions.for_user(author)
            if (
                author not in player.voice_client.channel.members
                and author_perms.skip_when_absent
            ):
                if not notice_sent:
                    res = Response(
                        _D(
                            "Skipping songs added by %(user)s as they are not in voice!",
                            self.server_data[guild.id],
                        )
                        % {"user": author.name},
                    )
                    await self.safe_send_message(channel, res)
                    notice_sent = True
                deleted_entry = player.playlist.delete_entry_at_index(0)
                log.noise(  # type: ignore[attr-defined]
                    "Author `%(user)s` absent, skipped (deleted) entry from queue:  %(song)s",
                    {"user": author.name, "song": deleted_entry.title},
                )
            else:
                break

        # manage auto playlist playback.
        if (
            not player.playlist.entries
            and not player.current_entry
            and self.config.auto_playlist
        ):
            # NOTE:  self.server_data[].autoplaylist will only contain links loaded from the file.
            #  while player.autoplaylist may contain links expanded from playlists.
            #  the only issue is that links from a playlist might fail and fire
            #  remove event, but no link will be removed since none will match.
            if not player.autoplaylist:
                if not self.server_data[guild.id].autoplaylist:
                    log.warning(
                        "No playable songs in the Guild autoplaylist, disabling."
                    )
                    self.config.auto_playlist = False
                else:
                    log.debug(
                        "No content in current autoplaylist. Filling with new music..."
                    )
                    player.autoplaylist = list(
                        self.server_data[player.voice_client.guild.id].autoplaylist
                    )

            while player.autoplaylist:
                log.everything(  # type: ignore[attr-defined]
                    "Looping over player autoplaylist..."
                )

                if not self.loop or (self.loop and self.loop.is_closed()):
                    log.debug("Event loop is closed, nothing else to do here.")
                    return

                if self.logout_called:
                    log.debug("Logout under way, ignoring this event.")
                    return

                if self.config.auto_playlist_random:
                    random.shuffle(player.autoplaylist)
                    song_url = random.choice(player.autoplaylist)
                else:
                    song_url = player.autoplaylist[0]
                player.autoplaylist.remove(song_url)

                # Check if song is blocked.
                if (
                    self.config.song_blocklist_enabled
                    and self.config.song_blocklist.is_blocked(song_url)
                ):
                    if self.config.auto_playlist_remove_on_block:
                        await self.server_data[guild.id].autoplaylist.remove_track(
                            song_url,
                            ex=UserWarning("Found in song block list."),
                            delete_from_ap=True,
                        )
                    continue

                try:
                    info = await self.downloader.extract_info(
                        song_url, download=False, process=True
                    )

                except (
                    youtube_dl.utils.DownloadError,
                    youtube_dl.utils.YoutubeDLError,
                ) as e:
                    log.error(
                        'Error while processing song "%(url)s":  %(raw_error)s',
                        {"url": song_url, "raw_error": e},
                    )

                    await self.server_data[guild.id].autoplaylist.remove_track(
                        song_url, ex=e, delete_from_ap=self.config.remove_ap
                    )
                    continue

                except exceptions.ExtractionError as e:
                    log.error(
                        'Error extracting song "%(url)s": %(raw_error)s',
                        {
                            "url": song_url,
                            "raw_error": _L(e.message) % e.fmt_args,
                        },
                        exc_info=True,
                    )

                    await self.server_data[guild.id].autoplaylist.remove_track(
                        song_url, ex=e, delete_from_ap=self.config.remove_ap
                    )
                    continue

                except exceptions.MusicbotException:
                    log.exception(
                        "MusicBot needs to stop the auto playlist extraction and bail."
                    )
                    return
                except Exception:  # pylint: disable=broad-exception-caught
                    log.exception(
                        "MusicBot got an unhandled exception in player finished event."
                    )
                    break

                if info.has_entries:
                    log.info(
                        "Expanding auto playlist with entries extracted from:  %s",
                        info.url,
                    )
                    entries = info.get_entries_objects()
                    pl_urls: List[str] = []
                    for entry in entries:
                        pl_urls.append(entry.url)

                    player.autoplaylist = pl_urls + player.autoplaylist
                    continue

                try:
                    await player.playlist.add_entry_from_info(
                        info,
                        channel=None,
                        author=None,
                        head=False,
                    )
                except (
                    # TODO: find usages of these and make sure they get translated.
                    exceptions.ExtractionError,
                    exceptions.WrongEntryTypeError,
                ) as e:
                    log.error(
                        "Error adding song from autoplaylist: %s",
                        _L(e.message) % e.fmt_args,
                    )
                    log.debug("Exception data for above error:", exc_info=True)
                    continue
                break
            # end of autoplaylist loop.

            if not self.server_data[guild.id].autoplaylist:
                log.warning("No playable songs in the autoplaylist, disabling.")
                self.config.auto_playlist = False

        else:  # Don't serialize for autoplaylist events
            await self.serialize_queue(guild)

        if not player.is_dead and not player.current_entry and len(player.playlist):
            player.play(_continue=True)

    async def on_player_entry_added(
        self,
        player: MusicPlayer,
        playlist: Playlist,
        entry: EntryTypes,
        defer_serialize: bool = False,
        **_: Any,
    ) -> None:
        """
        Event called by MusicPlayer when an entry is added to the playlist.
        """
        log.debug("Running on_player_entry_added")
        # if playing auto-playlist track and a user queues a track,
        # if we're configured to do so, auto skip the auto playlist track.
        if (
            self.config.auto_playlist_autoskip
            and player.current_entry
            and player.current_entry.from_auto_playlist
            and playlist.peek() == entry
            and not entry.from_auto_playlist
        ):
            log.debug("Automatically skipping auto-playlist entry for queued entry.")
            player.skip()

        # Only serialize the queue for user-added tracks, unless deferred
        if entry.author and entry.channel and not defer_serialize:
            await self.serialize_queue(player.voice_client.channel.guild)

    async def on_player_error(
        self,
        player: MusicPlayer,
        entry: Optional[EntryTypes],
        ex: Optional[Exception],
        **_: Any,
    ) -> None:
        """
        Event called by MusicPlayer when an entry throws an error.
        """
        # Log the exception according to entry or bare error.
        if entry is not None:
            log.exception(
                "MusicPlayer exception for entry: %r",
                entry,
                exc_info=ex,
            )
        else:
            log.exception(
                "MusicPlayer exception.",
                exc_info=ex,
            )

        # Send a message to the calling channel if we can.
        if entry and entry.channel:
            ssd = self.server_data[player.voice_client.guild.id]
            song = _D(entry.title, ssd) or entry.url
            if isinstance(ex, exceptions.MusicbotException):
                error = _D(ex.message, ssd) % ex.fmt_args
            else:
                error = str(ex)
            res = ErrorResponse(
                _D(
                    "Playback failed for song `%(song)s` due to an error:\n```\n%(error)s```",
                    ssd,
                )
                % {"song": song, "error": error},
                delete_after=self.config.delete_delay_long,
            )
            await self.safe_send_message(entry.channel, res)

        # Take care of auto-playlist related issues.
        if entry and entry.from_auto_playlist:
            log.info("Auto playlist track could not be played:  %r", entry)
            guild = player.voice_client.guild
            await self.server_data[guild.id].autoplaylist.remove_track(
                entry.info.input_subject, ex=ex, delete_from_ap=self.config.remove_ap
            )

        # If the party isn't rockin', don't bother knockin on my door.
        if not player.is_dead:
            if len(player.playlist):
                player.play(_continue=True)
            elif self.config.auto_playlist:
                await self.on_player_finished_playing(player)

    async def update_now_playing_status(self, set_offline: bool = False) -> None:
        """Inspects available players and ultimately fire change_presence()"""
        activity = None  # type: Optional[discord.BaseActivity]
        status = discord.Status.online  # type: discord.Status
        # NOTE:  Bots can only set: name, type, state, and url fields of activity.
        # Even though Custom type is available, we cannot use emoji field with bots.
        # So Custom Activity is effectively useless at time of writing.
        # Streaming Activity is a coin toss at best. Usually status changes correctly.
        # However all other details in the client might be wrong or missing.
        # Example:  Youtube url shows "Twitch" in client profile info.

        # if requested, try to set the bot offline.
        if set_offline:
            activity = discord.Activity(
                type=discord.ActivityType.custom,
                state="",
                name="Custom Status",  # seemingly required.
            )
            await self.change_presence(
                status=discord.Status.invisible, activity=activity
            )
            self.last_status = activity
            return

        # We ignore player related status when logout is called.
        if self.logout_called:
            log.debug("Logout under way, ignoring status update event.")
            return

        playing = sum(1 for p in self.players.values() if p.is_playing)
        if self.config.status_include_paused:
            paused = sum(1 for p in self.players.values() if p.is_paused)
            total = len(self.players)
        else:
            paused = 0
            total = playing

        def format_status_msg(player: Optional[MusicPlayer]) -> str:
            msg = self.config.status_message
            msg = msg.replace("{n_playing}", str(playing))
            msg = msg.replace("{n_paused}", str(paused))
            msg = msg.replace("{n_connected}", str(total))
            if player and player.current_entry:
                msg = msg.replace("{p0_title}", player.current_entry.title)
                msg = msg.replace(
                    "{p0_length}",
                    format_song_duration(player.current_entry.duration_td),
                )
                msg = msg.replace("{p0_url}", player.current_entry.url)
            else:
                msg = msg.replace("{p0_title}", "")
                msg = msg.replace("{p0_length}", "")
                msg = msg.replace("{p0_url}", "")
            return msg

        # multiple servers are playing or paused.
        if total > 1:
            if paused > playing:
                status = discord.Status.idle

            text = f"music on {total} servers"
            if self.config.status_message:
                player = None
                for p in self.players.values():
                    if p.is_playing:
                        player = p
                        break
                text = format_status_msg(player)

            activity = discord.Activity(
                type=discord.ActivityType.playing,
                name=text,
            )

        # only 1 server is playing.
        elif playing:
            player = None
            for p in self.players.values():
                if p.is_playing:
                    player = p
                    break
            if player and player.current_entry:
                text = player.current_entry.title.strip()[:128]
                if self.config.status_message:
                    text = format_status_msg(player)

                activity = discord.Activity(
                    type=discord.ActivityType.streaming,
                    url=player.current_entry.url,
                    name=text,
                )

        # only 1 server is paused.
        elif paused:
            player = None
            for p in self.players.values():
                if p.is_paused:
                    player = p
                    break
            if player and player.current_entry:
                text = player.current_entry.title.strip()[:128]
                if self.config.status_message:
                    text = format_status_msg(player)

                status = discord.Status.idle
                activity = discord.Activity(
                    type=discord.ActivityType.custom,
                    state=text,
                    name="Custom Status",  # seemingly required.
                )

        # nothing going on.
        else:
            text = f" ~ {EMOJI_IDLE_ICON} ~ "
            if self.config.status_message:
                text = format_status_msg(None)

            status = discord.Status.idle
            activity = discord.CustomActivity(
                type=discord.ActivityType.custom,
                state=text,
                name="Custom Status",  # seems required to make idle status work.
            )

        async with self.aiolocks[_func_()]:
            if activity != self.last_status:
                log.noise(  # type: ignore[attr-defined]
                    "Update bot status:  %(status)s -- %(activity)r",
                    {"status": status, "activity": activity},
                )
                await self.change_presence(status=status, activity=activity)
                self.last_status = activity
                # Discord docs say Game status can only be updated 5 times in 20 seconds.
                # This sleep should maintain the above lock for long enough to space
                # out the status updates in multi-guild setups.
                # If not, we should use the lock to ignore further updates.
                try:
                    await asyncio.sleep(4)
                except asyncio.CancelledError:
                    pass

    async def serialize_queue(self, guild: discord.Guild) -> None:
        """
        Serialize the current queue for a server's player to json.
        """
        if not self.config.persistent_queue:
            return

        player = self.get_player_in(guild)
        if not player:
            return

        path = self.config.data_path.joinpath(str(guild.id), DATA_GUILD_FILE_QUEUE)

        async with self.aiolocks["queue_serialization" + ":" + str(guild.id)]:
            log.debug("Serializing queue for %s", guild.id)

            with open(path, "w", encoding="utf8") as f:
                f.write(player.serialize(sort_keys=True))

    async def deserialize_queue(
        self,
        guild: discord.Guild,
        voice_client: discord.VoiceClient,
        playlist: Optional[Playlist] = None,
    ) -> Optional[MusicPlayer]:
        """
        Deserialize a saved queue for a server into a MusicPlayer.  If no queue is saved, returns None.
        """
        if not self.config.persistent_queue:
            return None

        if playlist is None:
            playlist = Playlist(self)

        path = self.config.data_path.joinpath(str(guild.id), DATA_GUILD_FILE_QUEUE)

        async with self.aiolocks["queue_serialization:" + str(guild.id)]:
            if not path.is_file():
                return None

            log.debug("Deserializing queue for %s", guild.id)

            with open(path, "r", encoding="utf8") as f:
                data = f.read()

        return MusicPlayer.from_json(data, self, voice_client, playlist)

    async def write_current_song(self, guild: discord.Guild, entry: EntryTypes) -> None:
        """
        Writes the current song to file
        """
        player = self.get_player_in(guild)
        if not player:
            return

        path = self.config.data_path.joinpath(str(guild.id), DATA_GUILD_FILE_CUR_SONG)

        async with self.aiolocks["current_song:" + str(guild.id)]:
            log.debug("Writing current song for %s", guild.id)

            with open(path, "w", encoding="utf8") as f:
                f.write(entry.title)

    #######################################################################################################################

    async def safe_send_message(
        self,
        dest: discord.abc.Messageable,
        content: MusicBotResponse,
    ) -> Optional[discord.Message]:
        """
        Safely send a message with given `content` to the message-able
        object in `dest`
        This method should handle all raised exceptions so callers will
        not need to handle them locally.

        :param: dest:     A channel, user, or other discord.abc.Messageable object.
        :param: content:  A MusicBotMessage such as Response or ErrorResponse.

        :returns:  May return a discord.Message object if a message was sent.
        """
        if not isinstance(content, MusicBotResponse):
            log.error(
                "Cannot send non-response object:  %r",
                content,
                exc_info=self.config.debug_mode,
            )
            raise exceptions.MusicbotException(
                "[Dev Bug] Tried sending an invalid response object."
            )

        fallback_channel = content.sent_from
        delete_after = content.delete_after
        reply_to = content.reply_to

        # set the default delete delay to configured short delay.
        if delete_after is None:
            delete_after = self.config.delete_delay_short

        msg = None
        retry_after = 0.0
        send_kws: Dict[str, Any] = {}

        ch_name = "DM-Channel"
        if hasattr(dest, "name"):
            ch_name = str(dest.name)

        if reply_to and reply_to.channel == dest:
            send_kws["reference"] = reply_to.to_reference(fail_if_not_exists=False)
            send_kws["mention_author"] = True

        if content.files:
            send_kws["files"] = content.files

        try:
            if (self.config.embeds and not content.force_text) or content.force_embed:
                log.debug("sending embed to: %s", dest)
                msg = await dest.send(embed=content, **send_kws)
            else:
                log.debug("sending text to: %s", dest)
                msg = await dest.send(content.to_markdown(), **send_kws)

        except discord.Forbidden:
            log.error(
                'Cannot send message to "%s", no permission',
                ch_name,
                exc_info=self.config.debug_mode,
            )

        except discord.NotFound:
            log.error(
                'Cannot send message to "%s", invalid or deleted channel',
                ch_name,
                exc_info=self.config.debug_mode,
            )

        except discord.HTTPException as e:
            if len(content) > DISCORD_MSG_CHAR_LIMIT:
                log.error(
                    "Message is over the message size limit (%s)",
                    DISCORD_MSG_CHAR_LIMIT,
                    exc_info=self.config.debug_mode,
                )

            # if `dest` is a user with strict privacy or a bot, direct message can fail.
            elif e.code == 50007 and fallback_channel:
                log.debug(
                    "Could not send private message, sending in fallback channel instead."
                )
                await self.safe_send_message(fallback_channel, content)

            # If we got rate-limited, retry using the retry-after api header.
            elif e.status == 429:
                # Note:  `e.response` could be either type:  aiohttp.ClientResponse  OR  requests.Response
                # thankfully both share a similar enough `response.headers` member CI Dict.
                # See docs on headers here:  https://discord.com/developers/docs/topics/rate-limits
                try:
                    retry_after = 0.0
                    header_val = e.response.headers.get("RETRY-AFTER")
                    if header_val:
                        retry_after = float(header_val)
                except ValueError:
                    retry_after = 0.0
                if retry_after:
                    log.warning(
                        "Rate limited send message, retrying in %s seconds.",
                        retry_after,
                    )
                    try:
                        await asyncio.sleep(retry_after)
                    except asyncio.CancelledError:
                        log.warning("Cancelled message retry for:  %s", content)
                        return msg
                    return await self.safe_send_message(dest, content)

                log.error(
                    "Rate limited send message, but cannot retry!",
                    exc_info=self.config.debug_mode,
                )

            else:
                log.error(
                    "Failed to send message in fallback channel.",
                    exc_info=self.config.debug_mode,
                )

        except aiohttp.client_exceptions.ClientError:
            log.error("Failed to send due to an HTTP error.")

        finally:
            if not retry_after and self.config.delete_messages and msg and delete_after:
                self.create_task(self._wait_delete_msg(msg, delete_after))

        return msg

    async def safe_delete_message(
        self,
        message: discord.Message,
    ) -> None:
        """
        Safely delete the given `message` from discord.
        This method should handle all raised exceptions so callers will
        not need to handle them locally.

        :param: quiet:  Toggle using log.debug or log.warning
        """
        # TODO: this could use a queue and some other handling.

        try:
            await message.delete()

        except discord.Forbidden:
            log.warning(
                'Cannot delete message "%s", no permission', message.clean_content
            )

        except discord.NotFound:
            log.warning(
                'Cannot delete message "%s", message not found',
                message.clean_content,
            )

        except discord.HTTPException as e:
            if e.status == 429:
                # Note:  `e.response` could be either type:  aiohttp.ClientResponse  OR  requests.Response
                # thankfully both share a similar enough `response.headers` member CI Dict.
                # See docs on headers here:  https://discord.com/developers/docs/topics/rate-limits
                try:
                    retry_after = 0.0
                    header_val = e.response.headers.get("RETRY-AFTER")
                    if header_val:
                        retry_after = float(header_val)
                except ValueError:
                    retry_after = 0.0
                if retry_after:
                    log.warning(
                        "Rate limited message delete, retrying in %s seconds.",
                        retry_after,
                    )
                    self.create_task(self._wait_delete_msg(message, retry_after))
                else:
                    log.error("Rate limited message delete, but cannot retry!")

            else:
                log.warning("Failed to delete message")
                log.noise(  # type: ignore[attr-defined]
                    "Got HTTPException trying to delete message: %s", message
                )

        except aiohttp.client_exceptions.ClientError:
            log.error(
                "Failed to send due to an HTTP error.", exc_info=self.config.debug_mode
            )

        return None

    async def safe_edit_message(
        self,
        message: discord.Message,
        new: MusicBotResponse,
        *,
        send_if_fail: bool = False,
    ) -> Optional[discord.Message]:
        """
        Safely update the given `message` with the `new` content.
        This function should handle all raised exceptions so callers
        will not need to handle them locally.

        :param: send_if_fail:  Toggle sending a new message if edit fails.
        :param: quiet:  Use log.debug if quiet otherwise use log.warning

        :returns:  May return a discord.Message object if edit/send did not fail.
        """
        try:
            if isinstance(new, discord.Embed):
                return await message.edit(embed=new)

            return await message.edit(content=new)

        except discord.NotFound:
            log.warning(
                'Cannot edit message "%s", message not found',
                message.clean_content,
            )
            if send_if_fail:
                log.warning("Sending message instead")
                return await self.safe_send_message(message.channel, new)

        except discord.HTTPException as e:
            if e.status == 429:
                # Note:  `e.response` could be either type:  aiohttp.ClientResponse  OR  requests.Response
                # thankfully both share a similar enough `response.headers` member CI Dict.
                # See docs on headers here:  https://discord.com/developers/docs/topics/rate-limits
                try:
                    retry_after = 0.0
                    header_val = e.response.headers.get("RETRY-AFTER")
                    if header_val:
                        retry_after = float(header_val)
                except ValueError:
                    retry_after = 0.0
                if retry_after:
                    log.warning(
                        "Rate limited edit message, retrying in %s seconds.",
                        retry_after,
                    )
                    try:
                        await asyncio.sleep(retry_after)
                    except asyncio.CancelledError:
                        log.warning("Cancelled message edit for:  %s", message)
                        return None
                    return await self.safe_edit_message(
                        message, new, send_if_fail=send_if_fail
                    )
            else:
                log.warning("Failed to edit message")
                log.noise(  # type: ignore[attr-defined]
                    "Got HTTPException trying to edit message %s to: %s", message, new
                )

        except aiohttp.client_exceptions.ClientError:
            log.error(
                "Failed to send due to an HTTP error.", exc_info=self.config.debug_mode
            )

        return None

    async def _wait_delete_msg(
        self, message: discord.Message, after: Union[int, float]
    ) -> None:
        """
        Uses asyncio.sleep to delay a call to safe_delete_message but
        does not check if the bot can delete a message or if it has
        already been deleted before trying to delete it anyway.
        """
        try:
            await asyncio.sleep(after)
        except asyncio.CancelledError:
            log.warning(
                "Cancelled delete for message (ID: %(id)s):  %(content)s",
                {"id": message.id, "content": message.content},
            )
            return

        if not self.is_closed():
            await self.safe_delete_message(message)

    def _setup_windows_signal_handler(self) -> None:
        """
        Windows needs special handling for Ctrl+C signals to play nice with asyncio
        so this method sets up signals with access to bot event loop.
        This enables capturing KeyboardInterrupt and using it to cleanly shut down.
        """
        if os.name != "nt":
            return

        # method used to set the above member.
        def set_windows_signal(sig: int, _frame: Any) -> None:
            self._os_signal = signal.Signals(sig)

        # method used to periodically check for a signal, and process it.
        async def check_windows_signal() -> None:
            while True:

                if self.logout_called:
                    break
                if self._os_signal is None:
                    try:
                        await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        break
                else:
                    await self.on_os_signal(self._os_signal, self.loop)
                    self._os_signal = None

        # register interrupt signal Ctrl+C to be trapped.
        signal.signal(signal.SIGINT, set_windows_signal)
        # and start the signal checking loop.
        task_ref = asyncio.create_task(
            check_windows_signal(), name="MB_WinInteruptChecker"
        )
        setattr(self, "_mb_win_sig_checker_task", task_ref)

    async def on_os_signal(
        self, sig: signal.Signals, _loop: asyncio.AbstractEventLoop
    ) -> None:
        """
        On Unix-like/Linux OS, this method is called automatically on the event
        loop for signals registered in run.py.
        On Windows, this method is called by custom signal handling set up at
        the start of run_musicbot().
        This allows MusicBot to handle external signals and triggering a clean
        shutdown of MusicBot in response to them.

        It essentially just calls logout, and the rest of MusicBot tear-down is
        finished up in `MusicBot.run_musicbot()` instead.

        Signals handled here are registered with the event loop in run.py.
        """
        # This print facilitates putting '^C' on its own line in the terminal.
        print()
        log.warning("Caught a signal from the OS: %s", sig.name)

        try:
            if self and not self.logout_called:
                log.info("Disconnecting and closing down MusicBot...")
                await self.logout()
        except Exception as e:
            log.exception("Exception thrown while handling interrupt signal!")
            raise KeyboardInterrupt() from e

    async def run_musicbot(self) -> None:
        """
        This method is to be used in an event loop to start the MusicBot.
        It handles cleanup of bot session, while the event loop is closed separately.
        """
        # Windows specifically needs some help with signals.
        self._setup_windows_signal_handler()

        # handle start up and teardown.
        try:
            log.info("MusicBot is now doing start up steps...")
            await self.start(*self.config.auth)
            log.info("MusicBot is now doing shutdown steps...")
            if self.exit_signal is None:
                self.exit_signal = exceptions.TerminateSignal()

        except discord.errors.LoginFailure as e:
            log.warning("Start up failed at login.")
            raise exceptions.HelpfulError(
                # fmt: off
                "Failed Discord API Login!\n"
                "\n"
                "Problem:\n"
                "  MusicBot could not log into Discord API.\n"
                "  Your Token may be incorrect or there may be an API outage.\n"
                "\n"
                "Solution:\n"
                "  Make sure you have the correct Token set in your config.\n"
                "  Check API status at the official site: discordstatus.com"
                # fmt: on
            ) from e

        finally:
            # Shut down the thread pool executor.
            log.info("Waiting for download threads to finish up...")
            # We can't kill the threads in ThreadPoolExecutor.  User can Ctrl+C though.
            # We can pass `wait=False` and carry on with "shutdown" but threads
            # will stay until they're done.  We wait to keep it clean...
            tps_args: Dict[str, Any] = {}
            if sys.version_info >= (3, 9):
                tps_args["cancel_futures"] = True
            self.downloader.thread_pool.shutdown(**tps_args)

            # Inspect all waiting tasks and either cancel them or let them finish.
            pending_tasks = []
            for task in asyncio.all_tasks(loop=self.loop):
                # Don't cancel run_musicbot task, we need it to finish cleaning.
                if task == asyncio.current_task():
                    continue

                tname = task.get_name()
                coro = task.get_coro()
                coro_name = "[unknown]"
                if coro and hasattr(coro, "__qualname__"):
                    coro_name = getattr(coro, "__qualname__", "[unknown]")

                if tname.startswith("Signal_SIG") or coro_name.startswith(
                    "Client.close."
                ):
                    log.debug(
                        "Will wait for task:  %(name)s  (%(func)s)",
                        {"name": tname, "func": coro_name},
                    )
                    pending_tasks.append(task)

                else:
                    log.debug(
                        "Will try to cancel task:  %(name)s  (%(func)s)",
                        {"name": tname, "func": coro_name},
                    )
                    task.cancel()
                    pending_tasks.append(task)

            # wait on any pending tasks.
            if pending_tasks:
                log.debug("Awaiting pending tasks...")
                await asyncio.gather(*pending_tasks, return_exceptions=True)
                await asyncio.sleep(0.5)

            # ensure connector is closed.
            if self.http.connector:
                log.debug("Closing HTTP Connector.")
                await self.http.connector.close()
                await asyncio.sleep(0.5)

            # ensure the session is closed.
            if self.session:
                log.debug("Closing aiohttp session.")
                await self.session.close()
                await asyncio.sleep(0.5)

            # if anything set an exit signal, we should raise it here.
            if self.exit_signal:
                raise self.exit_signal

    async def logout(self) -> None:
        """
        Disconnect all voice clients and signal MusicBot to close it's connections to discord.
        """
        log.noise("Logout has been called.")  # type: ignore[attr-defined]
        await self.update_now_playing_status(set_offline=True)

        self.logout_called = True
        await self.disconnect_all_voice_clients()
        return await super().close()

    async def on_error(self, event: str, /, *_args: Any, **_kwargs: Any) -> None:
        _ex_type, ex, _stack = sys.exc_info()

        if isinstance(ex, exceptions.HelpfulError):
            log.error(
                "Exception in %(event)s:\n%(error)s",
                {
                    "event": event,
                    "error": _L(ex.message) % ex.fmt_args,
                },
            )

            await asyncio.sleep(2)  # makes extra sure this gets seen(?)

            await self.logout()

        elif isinstance(ex, (exceptions.RestartSignal, exceptions.TerminateSignal)):
            self.exit_signal = ex
            await self.logout()

        else:
            log.error("Exception in %s", event, exc_info=True)

    async def on_resumed(self) -> None:
        """
        Event called by discord.py when the client resumed an existing session.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_resume
        """
        log.info("MusicBot resumed a session with discord.")
        await self._auto_join_channels(from_resume=True)

    async def on_ready(self) -> None:
        """
        Event called by discord.py typically when MusicBot has finished login.
        May be called multiple times, and may not be the first event dispatched!
        See documentations for specifics:
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_ready
        """
        if self.on_ready_count == 0:
            await self._on_ready_once()
            self.init_ok = True

        await self._on_ready_always()
        self.on_ready_count += 1

        log.debug("Finish on_ready")

    async def _on_ready_once(self) -> None:
        """
        A version of on_ready that will only ever be called once, at first login.
        """
        mute_discord_console_log()
        log.debug("Logged in, now getting MusicBot ready...")

        if not self.user:
            log.critical("ClientUser is somehow none, we gotta bail...")
            self.exit_signal = exceptions.TerminateSignal()
            raise self.exit_signal

        # Start the environment checks. Generate folders/files dependent on Discord data.
        # Also takes care of app-info and auto OwnerID updates.
        await self._on_ready_sanity_checks()

        log.info(
            "MusicBot:  %(id)s/%(name)s#%(desc)s",
            {
                "id": self.user.id,
                "name": self.user.name,
                "desc": self.user.discriminator,
            },
        )

        owner = self._get_owner_member()
        if owner and self.guilds:
            log.info(
                "Owner:     %(id)s/%(name)s#%(desc)s\n",
                {
                    "id": owner.id,
                    "name": owner.name,
                    "desc": owner.discriminator,
                },
            )

            log.info("Guild List:")
            unavailable_servers = 0
            for s in self.guilds:
                ser = f"{s.name} (unavailable)" if s.unavailable else s.name
                log.info(" - %s", ser)
                if self.config.leavenonowners:
                    if s.unavailable:
                        unavailable_servers += 1
                    else:
                        check = s.get_member(owner.id)
                        if check is None:
                            await s.leave()
                            log.info(
                                "Left %s due to bot owner not found",
                                s.name,
                            )
            if unavailable_servers != 0:
                log.info(
                    "Not proceeding with checks in %s servers due to unavailability",
                    str(unavailable_servers),
                )

        elif self.guilds:
            log.warning(
                "Owner could not be found on any guild (id: %s)\n", self.config.owner_id
            )

            log.info("Guild List:")
            for s in self.guilds:
                ser = f"{s.name} (unavailable)" if s.unavailable else s.name
                log.info(" - %s", ser)

        else:
            log.warning("Owner unknown, bot is not on any guilds.")
            if self.user.bot:
                invite_url = await self.generate_invite_link()
                log.warning(
                    "To make the bot join a guild, paste this link in your browser. \n"
                    "Note: You should be logged into your main account and have \n"
                    "manage server permissions on the guild you want the bot to join.\n"
                    "  %s",
                    invite_url,
                )

        print(flush=True)

        # validate bound channels and log them.
        if self.config.bound_channels:
            # Get bound channels by ID, and validate that we can use them.
            text_chlist: Set[MessageableChannel] = set()
            invalid_ids: Set[int] = set()
            for ch_id in self.config.bound_channels:
                ch = self.get_channel(ch_id)
                if not ch:
                    log.warning("Got None for bound channel with ID:  %d", ch_id)
                    invalid_ids.add(ch_id)
                    continue

                if not isinstance(ch, discord.abc.Messageable):
                    log.warning(
                        "Cannot bind to non Messageable channel with ID:  %d",
                        ch_id,
                    )
                    invalid_ids.add(ch_id)
                    continue

                if not isinstance(ch, (discord.PartialMessageable, discord.DMChannel)):
                    text_chlist.add(ch)

            # Clean up our config data so it can be reliable later.
            self.config.bound_channels.difference_update(invalid_ids)

            # finally, log what we've bound to.
            if text_chlist:
                log.info("Bound to text channels:")
                for valid_ch in text_chlist:
                    guild_name = _L("Private Channel")
                    if isinstance(valid_ch, discord.DMChannel):
                        ch_name = _L("Unknown User DM")
                        if valid_ch.recipient:
                            ch_name = _L("User DM: %(name)s") % {
                                "name": valid_ch.recipient.name
                            }
                    elif isinstance(valid_ch, discord.PartialMessageable):
                        ch_name = _L("Unknown Channel (Partial)")
                    else:
                        ch_name = valid_ch.name or _L("Unnamed Channel: %(id)s") % {
                            "id": valid_ch.id
                        }
                    if valid_ch.guild:
                        guild_name = valid_ch.guild.name
                    log.info(
                        " - %(guild)s/%(channel)s",
                        {"guild": guild_name, "channel": ch_name},
                    )
            else:
                log.info("Not bound to any text channels")
        else:
            log.info("Not bound to any text channels")

        print(flush=True)  # new line in console.

        # validate and display auto-join channels.
        if self.config.autojoin_channels:
            vc_chlist: Set[VoiceableChannel] = set()
            invalids: Set[int] = set()
            for ch_id in self.config.autojoin_channels:
                ch = self.get_channel(ch_id)
                if not ch:
                    log.warning("Got None for auto join channel with ID:  %d", ch_id)
                    invalids.add(ch_id)
                    continue

                if isinstance(ch, discord.abc.PrivateChannel):
                    log.warning(
                        "Cannot auto join a Private/Non-Guild channel with ID:  %d",
                        ch_id,
                    )
                    invalids.add(ch_id)
                    continue

                if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
                    log.warning(
                        "Cannot auto join to non-connectable channel with ID:  %d",
                        ch_id,
                    )
                    invalids.add(ch_id)
                    continue

                # Add the channel to vc_chlist for log readout.
                vc_chlist.add(ch)
                # Add the channel to guild-specific auto-join slot.
                self.server_data[ch.guild.id].auto_join_channel = ch

            # Update config data to be reliable later.
            self.config.autojoin_channels.difference_update(invalids)

            # log what we're connecting to.
            if vc_chlist:
                log.info("Auto joining voice channels:")
                for ch in vc_chlist:
                    log.info(
                        " - %(guild)s/%(channel)s",
                        {"guild": ch.guild.name.strip(), "channel": ch.name.strip()},
                    )

            else:
                log.info("Not auto joining any voice channels")

        else:
            log.info("Not auto joining any voice channels")

        # Display and log the config settings.
        if self.config.show_config_at_start:
            self._on_ready_log_configs()

        # we do this after the config stuff because it's a lot easier to notice here
        if self.config.register.ini_missing_options:
            missing_list = "\n".join(
                sorted(str(o) for o in self.config.register.ini_missing_options)
            )
            log.warning(
                # fmt: off
                "Detected missing config options!\n"
                "\n"
                "Problem:\n"
                "  You config options file is missing some options.\n"
                "  Default settings will be used for these options.\n"
                "  Here is a list of options we didn't find:\n"
                "  %(missing)s\n"
                "\n"
                "Solution:\n"
                "  Copy new options from the example options file.\n"
                "  Or use the config command to set and save them.\n\n",
                # fmt: on
                {"missing": missing_list},
            )

        # Pre-load guild specific data / options.
        # TODO:  probably change this later for better UI/UX.
        if self.config.enable_options_per_guild:
            for guild in self.guilds:
                # Triggers on-demand task to load data from disk.
                self.server_data[guild.id].is_ready()
                # context switch to give scheduled task an execution window.
                await asyncio.sleep(0)

    async def _on_ready_always(self) -> None:
        """
        A version of on_ready that will be called on every event.
        """
        if self.on_ready_count > 0:
            log.debug("Event on_ready has fired %s times", self.on_ready_count)
        self.create_task(self._on_ready_call_later(), name="MB_PostOnReady")

    async def _on_ready_call_later(self) -> None:
        """
        A collection of calls scheduled for execution by _on_ready_once
        """
        await self.update_now_playing_status()
        await self._auto_join_channels()

    async def _on_ready_sanity_checks(self) -> None:
        """
        Run all sanity checks that should be run in/just after on_ready event.
        """
        # Ensure AppInfo is loaded.
        if not self.cached_app_info:
            log.debug("Getting application info.")
            self.cached_app_info = await self.application_info()

        # Ensure folders exist
        await self._on_ready_ensure_env()

        # TODO: Server permissions check
        # TODO: pre-expand playlists in autoplaylist?

        # Ensure configs are valid / auto OwnerID is updated.
        await self._on_ready_validate_configs()

    async def _on_ready_ensure_env(self) -> None:
        """
        Startup check to make sure guild/server specific directories are
        available in the data directory.
        Additionally populate a text file to map guild ID to their names.
        """
        log.debug("Ensuring data folders exist")
        for guild in self.guilds:
            self.config.data_path.joinpath(str(guild.id)).mkdir(exist_ok=True)

        names_path = self.config.data_path.joinpath(DATA_FILE_SERVERS)
        with open(names_path, "w", encoding="utf8") as f:
            for guild in sorted(self.guilds, key=lambda s: int(s.id)):
                f.write(f"{guild.id}: {guild.name}\n")

        self.filecache.delete_old_audiocache(remove_dir=True)

    async def _on_ready_validate_configs(self) -> None:
        """
        Startup check to handle late validation of config and permissions.
        """
        log.debug("Validating config")
        await self.config.async_validate(self)

        log.debug("Validating permissions config")
        await self.permissions.async_validate(self)

    def _on_ready_log_configs(self) -> None:
        """
        Shows information about configs, including missing keys.
        No validation is done in this method, only display/logs.
        """

        def on_or_off(test: bool) -> str:
            return [_L("Disabled"), _L("Enabled")][test]

        print(flush=True)
        log.info("Options:")

        log.info("  Command prefix: %s", self.config.command_prefix)
        log.info("  Default volume: %d%%", int(self.config.default_volume * 100))
        log.info(
            "  Skip threshold: %(num)d votes or %(percent).0f%%",
            {
                "num": self.config.skips_required,
                "percent": (self.config.skip_ratio_required * 100),
            },
        )
        log.info(
            "  Now Playing @mentions: %s",
            on_or_off(self.config.now_playing_mentions),
        )
        log.info("  Auto-Summon: %s", on_or_off(self.config.auto_summon))
        log.info(
            "  Auto-Playlist: %(status)s (order: %(order)s)",
            {
                "status": on_or_off(self.config.auto_playlist),
                "order": [_L("sequential"), _L("random")][
                    self.config.auto_playlist_random
                ],
            },
        )
        log.info("  Auto-Pause: %s", on_or_off(self.config.auto_pause))
        log.info(
            "  Delete Messages: %s",
            on_or_off(self.config.delete_messages),
        )
        if self.config.delete_messages:
            log.info(
                "    Delete Invoking: %s",
                on_or_off(self.config.delete_invoking),
            )
            log.info(
                "    Delete Now Playing: %s",
                on_or_off(self.config.delete_nowplaying),
            )
        log.info("  Debug Mode: %s", on_or_off(self.config.debug_mode))
        log.info(
            "  Downloaded songs will be %s",
            ["deleted", "saved"][self.config.save_videos],
        )
        if self.config.save_videos and self.config.storage_limit_days:
            log.info("    Delete if unused for %d days", self.config.storage_limit_days)
        if self.config.save_videos and self.config.storage_limit_bytes:
            size = format_size_from_bytes(self.config.storage_limit_bytes)
            log.info("    Delete if size exceeds %s", size)

        if self.config.status_message:
            log.info("  Status message: %s", self.config.status_message)
        log.info(
            "  Write current songs to file: %s",
            on_or_off(self.config.write_current_song),
        )
        log.info(
            "  Author insta-skip: %s",
            on_or_off(self.config.allow_author_skip),
        )
        log.info("  Embeds: %s", on_or_off(self.config.embeds))
        log.info(
            "  Spotify integration: %s",
            on_or_off(self.config.spotify_enabled),
        )
        log.info("  Legacy skip: %s", on_or_off(self.config.legacy_skip))
        log.info(
            "  Leave non owners: %s",
            on_or_off(self.config.leavenonowners),
        )
        log.info(
            "  Leave inactive VC: %s",
            on_or_off(self.config.leave_inactive_channel),
        )
        if self.config.leave_inactive_channel:
            log.info(
                "    Timeout: %s seconds",
                self.config.leave_inactive_channel_timeout,
            )
        log.info(
            "  Leave at song end/empty queue: %s",
            on_or_off(self.config.leave_after_queue_empty),
        )
        log.info(
            "  Leave when player idles: %s",
            "Disabled" if self.config.leave_player_inactive_for == 0 else "Enabled",
        )
        if self.config.leave_player_inactive_for:
            log.info("    Timeout: %d seconds", self.config.leave_player_inactive_for)
        log.info("  Self Deafen: %s", on_or_off(self.config.self_deafen))
        log.info(
            "  Per-server command prefix: %s",
            on_or_off(self.config.enable_options_per_guild),
        )
        log.info("  Search List: %s", on_or_off(self.config.searchlist))
        log.info(
            "  Round Robin Queue: %s",
            on_or_off(self.config.round_robin_queue),
        )
        print(flush=True)

    def _get_song_url_or_none(
        self, url: str, player: Optional[MusicPlayer]
    ) -> Optional[str]:
        """Return song url if provided or one is currently playing, else returns None"""
        url_or_none = self.downloader.get_url_or_none(url)
        if url_or_none:
            return url_or_none

        if player and player.current_entry and player.current_entry.url:
            return player.current_entry.url

        return None

    def _do_song_blocklist_check(self, song_subject: str) -> None:
        """
        Check if the `song_subject` is matched in the block list.

        :raises: musicbot.exceptions.CommandError
            The subject is matched by a block list entry.
        """
        if not self.config.song_blocklist_enabled:
            return

        if self.config.song_blocklist.is_blocked(song_subject):
            raise exceptions.CommandError(
                "The requested song `%(subject)s` is blocked by the song block list.",
                fmt_args={"subject": song_subject},
            )

    async def handle_vc_inactivity(self, guild: discord.Guild) -> None:
        """
        Manage a server-specific event timer when MusicBot's voice channel becomes idle,
        if the bot is configured to do so.
        """
        if not guild.voice_client or not guild.voice_client.channel:
            log.warning(
                "Attempted to handle Voice Channel inactivity, but Bot is not in voice..."
            )
            return

        event = self.server_data[guild.id].get_event("inactive_vc_timer")

        if event.is_active():
            log.debug("Channel activity already waiting in guild: %s", guild)
            return
        event.activate()

        try:
            chname = _L("Unknown Channel")
            if hasattr(guild.voice_client.channel, "name"):
                chname = guild.voice_client.channel.name

            log.info(
                "Channel activity waiting %(time)d seconds to leave channel: %(channel)s",
                {
                    "time": self.config.leave_inactive_channel_timeout,
                    "channel": chname,
                },
            )
            await discord.utils.sane_wait_for(
                [event.wait()], timeout=self.config.leave_inactive_channel_timeout
            )
        except asyncio.TimeoutError:
            # could timeout after a disconnect.
            if guild.voice_client and isinstance(
                guild.voice_client.channel, (discord.VoiceChannel, discord.StageChannel)
            ):
                log.info(
                    "Channel activity timer for %s has expired. Disconnecting.",
                    guild.name,
                )
                await self.on_inactivity_timeout_expired(guild.voice_client.channel)
        else:
            log.info(
                "Channel activity timer canceled for: %(channel)s in %(guild)s",
                {
                    "channel": getattr(
                        guild.voice_client.channel, "name", guild.voice_client.channel
                    ),
                    "guild": guild.name,
                },
            )
        finally:
            event.deactivate()
            event.clear()

    async def handle_player_inactivity(self, player: MusicPlayer) -> None:
        """
        Manage a server-specific event timer when it's MusicPlayer becomes idle,
        if the bot is configured to do so.
        """
        if self.logout_called:
            return

        if not self.config.leave_player_inactive_for:
            return
        channel = player.voice_client.channel
        guild = channel.guild
        event = self.server_data[guild.id].get_event("inactive_player_timer")

        if str(channel.id) in str(self.config.autojoin_channels):
            log.debug(
                "Ignoring player inactivity in auto-joined channel:  %s",
                channel.name,
            )
            return

        if event.is_active():
            log.debug(
                "Player activity timer already waiting in guild: %s",
                guild,
            )
            return
        event.activate()

        try:
            log.info(
                "Player activity timer waiting %(time)d seconds to leave channel: %(channel)s",
                {
                    "time": self.config.leave_player_inactive_for,
                    "channel": channel.name,
                },
            )
            await discord.utils.sane_wait_for(
                [event.wait()], timeout=self.config.leave_player_inactive_for
            )
        except asyncio.TimeoutError:
            if not player.is_playing and player.voice_client.is_connected():
                log.info(
                    "Player activity timer for %s has expired. Disconnecting.",
                    guild.name,
                )
                await self.on_inactivity_timeout_expired(channel)
            else:
                log.info(
                    "Player activity timer canceled for: %(channel)s in %(guild)s",
                    {"channel": channel.name, "guild": guild.name},
                )
        else:
            log.info(
                "Player activity timer canceled for: %(channel)s in %(guild)s",
                {"channel": channel.name, "guild": guild.name},
            )
        finally:
            event.deactivate()
            event.clear()

    async def reset_player_inactivity(self, player: MusicPlayer) -> None:
        """
        Handle reset of the server-specific inactive player timer if it is enabled.
        """
        if not self.config.leave_player_inactive_for:
            return
        guild = player.voice_client.channel.guild
        event = self.server_data[guild.id].get_event("inactive_player_timer")
        if event.is_active() and not event.is_set():
            event.set()
            log.debug("Player activity timer is being reset.")

    @command_helper(
        desc=_Dd(
            "Reset the auto playlist queue by copying it back into player memory.\n"
            "This command will be removed in a future version, replaced by the autoplaylist command(s)."
        )
    )
    async def cmd_resetplaylist(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        player: MusicPlayer,
    ) -> CommandResponse:
        """
        Deprecated command, to be replaced with autoplaylist restart sub-command.
        """
        player.autoplaylist = list(self.server_data[guild.id].autoplaylist)
        return Response(
            _D("\N{OK HAND SIGN}", ssd_),
            force_text=True,
        )

    @command_helper(
        usage=["{cmd} [COMMAND]"],
        desc=_Dd(
            "Show usage and description of a command, or list all available commands.\n"
        ),
    )
    async def cmd_help(
        self,
        ssd_: Optional[GuildSpecificData],
        message: discord.Message,
        guild: Optional[discord.Guild],
        command: Optional[str] = None,
    ) -> CommandResponse:
        """
        Display help text for usage of MusicBot or specific commmands.
        """
        commands = []
        is_all = False
        is_emoji = False
        alias_of = ""
        if not guild:
            prefix = self.config.command_prefix
        else:
            prefix = self.server_data[guild.id].command_prefix
        # Its OK to skip unicode emoji here, they render correctly inside of code boxes.
        emoji_regex = re.compile(r"^(<a?:.+:\d+>|:.+:)$")
        if emoji_regex.match(prefix):
            is_emoji = True

        def _get_aliases(cmd: str) -> str:
            aliases = ""
            if cmd and self.config.usealias:
                alias_list = self.aliases.for_command(cmd)
                if alias_list:
                    aliases = _D("**Aliases for this command:**\n", ssd_)
                    for alias in alias_list:
                        aliases += _D(
                            "`%(alias)s` alias of `%(command)s %(args)s`\n",
                            ssd_,
                        ) % {
                            "alias": alias[0],
                            "command": cmd,
                            "args": alias[1],
                        }
            return aliases

        if command:
            if command.lower() == "all":
                is_all = True
                commands = await self.gen_cmd_list(message, list_all_cmds=True)

            else:
                a_command = command
                cmd = getattr(self, "cmd_" + command, None)
                # check for aliases if natural command is not found.
                if not cmd and self.config.usealias:
                    a_command, alias_arg_str = self.aliases.from_alias(command)
                    cmd = getattr(self, "cmd_" + a_command, None)
                    if cmd:
                        alias_of = " ".join([a_command, alias_arg_str]).strip()

                aid = message.author.id
                if cmd and (
                    not hasattr(cmd, "dev_cmd")
                    or self.config.owner_id == aid
                    or aid in self.config.dev_ids
                ):
                    alias_usage = ""
                    if alias_of:
                        alias_usage = _D(
                            "**Alias of command:**\n  `%(command)s`\n", ssd_
                        ) % {
                            "command": alias_of,
                        }

                    return Response(
                        # TRANSLATORS: template string for command-specific help output.
                        _D("%(is_alias)s\n%(docs)s\n%(alias_list)s", ssd_)
                        % {
                            "is_alias": alias_usage,
                            "docs": await self.gen_cmd_help(a_command, guild),
                            "alias_list": _get_aliases(a_command),
                        },
                        delete_after=self.config.delete_delay_long,
                    )

                raise exceptions.CommandError("No such command")

        elif message.author.id == self.config.owner_id:
            commands = await self.gen_cmd_list(message, list_all_cmds=True)

        else:
            commands = await self.gen_cmd_list(message)

        example_help_cmd = f"`{prefix}help [COMMAND]`"
        example_help_all = f"`{prefix}help all`"
        if is_emoji:
            example_help_cmd = f"{prefix}`help [COMMAND]`"
            example_help_all = f"{prefix}`help all`"
        else:
            prefix = f"`{prefix}`"

        all_note = ""
        if not is_all:
            all_note = _D(
                "The list above shows only commands permitted for your use.\n"
                "For a list of all commands, run: %(example_all)s\n",
                ssd_,
            ) % {"example_all": example_help_all}

        desc = _D(
            "**Commands by name:** *(without prefix)*\n"
            "```\n%(command_list)s\n```\n"
            "**Command Prefix:** %(prefix)s\n\n"
            "For help with a particular command, run: %(example_command)s\n"
            "%(all_note)s",
            ssd_,
        ) % {
            "command_list": ", ".join(commands),
            "prefix": prefix,
            "example_command": example_help_cmd,
            "all_note": all_note,
        }

        return Response(desc, delete_after=self.config.delete_delay_long)

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} add <@USER>\n"
            + _Dd("    Block a mentioned user."),

            "{cmd} remove <@USER>\n"
            + _Dd("    Unblock a mentioned user."),

            "{cmd} status <@USER>\n"
            + _Dd("    Show the block status of a mentioned user."),
        ],
        # fmt: on
        desc=_Dd(
            "Manage the users in the user block list.\n"
            "Blocked users are forbidden from using all bot commands.\n"
        ),
        remap_subs={"+": "add", "-": "remove", "?": "status"},
    )
    async def cmd_blockuser(
        self,
        ssd_: Optional[GuildSpecificData],
        user_mentions: UserMentions,
        option: str,
        leftover_args: List[str],
    ) -> CommandResponse:
        """
        Usage:
            {command_prefix}blockuser [add | remove | status] @UserName [@UserName2 ...]

        Manage users in the block list.
        Blocked users are forbidden from using all bot commands.
        """

        if not user_mentions and not leftover_args:
            raise exceptions.CommandError(
                "You must mention a user or provide their ID number.",
            )

        if option not in ["+", "-", "?", "add", "remove", "status"]:
            raise exceptions.CommandError(
                "Invalid sub-command given. Use `help blockuser` for usage examples."
            )

        for p_user in leftover_args:
            if p_user.isdigit():
                u = self.get_user(int(p_user))
                if u:
                    user_mentions.append(u)

        if not user_mentions:
            raise exceptions.CommandError(
                "MusicBot could not find the user(s) you specified.",
            )

        for user in user_mentions.copy():
            if option in ["+", "add"] and self.config.user_blocklist.is_blocked(user):
                if user.id == self.config.owner_id:
                    raise exceptions.CommandError(
                        "The owner cannot be added to the block list."
                    )

                log.info(
                    "Not adding user to block list, already blocked:  %(id)s/%(name)s",
                    {"id": user.id, "name": user.name},
                )
                user_mentions.remove(user)

            if option in ["-", "remove"] and not self.config.user_blocklist.is_blocked(
                user
            ):
                log.info(
                    "Not removing user from block list, not listed:  %(id)s/%(name)s",
                    {"id": user.id, "name": user.name},
                )
                user_mentions.remove(user)

        # allow management regardless, but tell the user if it will apply.
        if self.config.user_blocklist_enabled:
            status_msg = _D("User block list is currently enabled.", ssd_)
        else:
            status_msg = _D("User block list is currently disabled.", ssd_)

        old_len = len(self.config.user_blocklist)
        user_ids = {str(user.id) for user in user_mentions}

        if option in ["+", "add"]:
            if not user_mentions:
                raise exceptions.CommandError(
                    "Cannot add the users you listed, they are already added."
                )

            async with self.aiolocks["user_blocklist"]:
                self.config.user_blocklist.append_items(user_ids)

            n_users = len(self.config.user_blocklist) - old_len
            return Response(
                _D(
                    "%(number)s user(s) have been added to the block list.\n"
                    "%(status)s",
                    ssd_,
                )
                % {
                    "number": n_users,
                    "status": status_msg,
                }
            )

        if self.config.user_blocklist.is_disjoint(user_mentions):
            return Response(_D("None of those users are in the blacklist.", ssd_))

        if option in ["?", "status"]:
            ustatus = ""
            for user in user_mentions:
                blocked = _D("User: `%(user)s` is not blocked.\n", ssd_)
                if self.config.user_blocklist.is_blocked(user):
                    blocked = _D("User: `%(user)s` is blocked.\n", ssd_)
                ustatus += blocked % {"user": user.name}
            return Response(
                _D("**Block list status:**\n%(status)s\n%(users)s", ssd_)
                % {"status": status_msg, "users": ustatus},
            )

        async with self.aiolocks["user_blocklist"]:
            self.config.user_blocklist.remove_items(user_ids)

        n_users = old_len - len(self.config.user_blocklist)
        return Response(
            _D(
                "%(number)s user(s) have been removed from the block list.\n%(status)s",
                ssd_,
            )
            % {"number": n_users, "status": status_msg}
        )

    @command_helper(
        usage=["{cmd} <add | remove> [SUBJECT]\n"],
        desc=_Dd(
            "Manage a block list applied to song requests and extracted song data.\n"
            "A subject may be a song URL or a word or phrase found in the track title.\n"
            "If subject is omitted, any currently playing track URL will be added instead.\n"
            "\n"
            "The song block list matches loosely, but is case-sensitive.\n"
            "This means adding 'Pie' will match 'cherry Pie' but not 'piecrust' in checks.\n"
        ),
        remap_subs={"+": "add", "-": "remove"},
    )
    async def cmd_blocksong(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        _player: Optional[MusicPlayer],
        option: str,
        leftover_args: List[str],
        song_subject: str = "",
    ) -> CommandResponse:
        """
        Command for managing the song block list.
        """
        if leftover_args:
            song_subject = " ".join([song_subject, *leftover_args])

        if not song_subject:
            valid_url = self._get_song_url_or_none(song_subject, _player)
            if not valid_url:
                raise exceptions.CommandError(
                    "You must provide a song subject if no song is currently playing.",
                )
            song_subject = valid_url

        if option not in ["+", "-", "add", "remove"]:
            raise exceptions.CommandError(
                "Invalid sub-command given. Use `help blocksong` for usage examples."
            )

        # allow management regardless, but tell the user if it will apply.
        if self.config.song_blocklist_enabled:
            status_msg = "Song block list is currently enabled."
        else:
            status_msg = "Song block list is currently disabled."

        if option in ["+", "add"]:
            if self.config.song_blocklist.is_blocked(song_subject):
                raise exceptions.CommandError(
                    "Subject `%(subject)s` is already in the song block list.",
                    fmt_args={"subject": song_subject},
                )

            # remove song from auto-playlist if it is blocked
            if (
                self.config.auto_playlist_remove_on_block
                and _player
                and _player.current_entry
                and song_subject == _player.current_entry.url
                and _player.current_entry.from_auto_playlist
            ):
                await self.server_data[guild.id].autoplaylist.remove_track(
                    song_subject,
                    ex=UserWarning("Removed and added to block list."),
                    delete_from_ap=True,
                )

            async with self.aiolocks["song_blocklist"]:
                self.config.song_blocklist.append_items([song_subject])

            return Response(
                _D(
                    "Added subject `%(subject)s` to the song block list.\n%(status)s",
                    ssd_,
                )
                % {"subject": song_subject, "status": status_msg}
            )

        # handle "remove" and "-"
        if not self.config.song_blocklist.is_blocked(song_subject):
            raise exceptions.CommandError(
                "The subject is not in the song block list and cannot be removed.",
            )

        async with self.aiolocks["song_blocklist"]:
            self.config.song_blocklist.remove_items([song_subject])

        return Response(
            _D(
                "Subject `%(subject)s` has been removed from the block list.\n%(status)s",
                ssd_,
            )
            % {"subject": song_subject, "status": status_msg}
        )

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} <add | remove> [URL]\n"
            + _Dd("    Adds or removes the specified song or currently playing song to/from the current playlist.\n"),

            "{cmd} add all\n"
            + _Dd("    Adds the entire queue to the guilds playlist.\n"),

            "{cmd} clear [NAME]\n"
            + _Dd(
                "    Clear all songs from the named playlist file.\n"
                "    If name is omitted, the currently loaded playlist is emptied.\n"
            ),

            "{cmd} show\n"
            + _Dd("    Show the currently selected playlist and a list of existing playlist files.\n"),

            "{cmd} restart\n"
            + _Dd(
                "    Reload the auto playlist queue, restarting at the first track unless randomized.\n"
            ),

            "{cmd} set <NAME>\n"
            + _Dd("    Set a playlist as default for this guild and reloads the guild auto playlist.\n"),

        ],
        # fmt: on
        desc=_Dd("Manage auto playlist files and per-guild settings."),
        remap_subs={"+": "add", "-": "remove"},
    )
    async def cmd_autoplaylist(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        author: discord.Member,
        _player: Optional[MusicPlayer],
        player: MusicPlayer,
        option: str,
        opt_url: str = "",
    ) -> CommandResponse:
        """
        Manage auto playlists globally and per-guild.
        """
        # TODO: add a method to display the current auto playlist setting in chat.
        option = option.lower()
        if option not in [
            "+",
            "-",
            "add",
            "remove",
            "clear",
            "show",
            "set",
            "restart",
            "queue",
        ]:
            raise exceptions.CommandError(
                "Invalid sub-command given. Use `help autoplaylist` for usage examples.",
            )

        def _get_url() -> str:
            url = self._get_song_url_or_none(opt_url, _player)

            if not url:
                raise exceptions.CommandError("The supplied song link is invalid")
            return url

        if option in ["+", "add"] and opt_url.lower() == "all":
            if not player.playlist.entries:
                raise exceptions.CommandError(
                    "The queue is empty. Add some songs with a play command!",
                )

            added_songs = set()
            for e in player.playlist.entries:
                if e.url not in self.server_data[guild.id].autoplaylist:
                    await self.server_data[guild.id].autoplaylist.add_track(e.url)
                    added_songs.add(e.url)

            if not added_songs:
                return Response(
                    _D("All songs in the queue are already in the autoplaylist.", ssd_)
                )

            return Response(
                _D("Added %(number)d songs to the autoplaylist.", ssd_)
                % {"number": len(added_songs)},
            )

        if option in ["+", "add"]:
            url = _get_url()
            self._do_song_blocklist_check(url)
            if url not in self.server_data[guild.id].autoplaylist:
                await self.server_data[guild.id].autoplaylist.add_track(url)
                return Response(
                    _D("Added `%(url)s` to the autoplaylist.", ssd_) % {"url": url},
                )
            raise exceptions.CommandError(
                "This song is already in the autoplaylist.",
            )

        if option in ["-", "remove"]:
            url = _get_url()
            if url in self.server_data[guild.id].autoplaylist:
                await self.server_data[guild.id].autoplaylist.remove_track(
                    url,
                    ex=UserWarning(
                        f"Removed by command from user:  {author.id}/{author.name}#{author.discriminator}"
                    ),
                    delete_from_ap=True,
                )
                return Response(
                    _D("Removed `%(url)s` from the autoplaylist.", ssd_) % {"url": url},
                )
            raise exceptions.CommandError(
                "This song is not yet in the autoplaylist.",
            )

        if option == "restart":
            apl = self.server_data[guild.id].autoplaylist
            await apl.load(force=True)
            player.autoplaylist = list(apl)
            return Response(
                _D(
                    "Loaded a fresh copy of the playlist: `%(file)s`",
                    ssd_,
                )
                % {"file": apl.filename}
            )

        if option == "show":
            self.playlist_mgr.discover_playlists()
            filename = " "
            if ssd_:
                filename = ssd_.autoplaylist.filename
            names = "\n".join([f"`{pl}`" for pl in self.playlist_mgr.playlist_names])
            return Response(
                _D(
                    "**Current Playlist:** `%(playlist)s`"
                    "**Available Playlists:**\n%(names)s",
                    ssd_,
                )
                % {"playlist": filename, "names": names},
                delete_after=self.config.delete_delay_long,
            )

        if option == "set":
            if not opt_url:
                raise exceptions.CommandError(
                    "You must provide a playlist filename.",
                )

            # Add file extension if one was not given.
            if not opt_url.lower().endswith(".txt"):
                opt_url += ".txt"

            # Update the server specific data.
            pl = self.playlist_mgr.get_playlist(opt_url)
            self.server_data[guild.id].autoplaylist = pl
            await self.server_data[guild.id].save_guild_options_file()
            await pl.load()

            # Update the player copy if needed.
            if _player and self.config.auto_playlist:
                _player.autoplaylist = list(pl)

            new_msg = ""
            if not self.playlist_mgr.playlist_exists(opt_url):
                new_msg = _D(
                    "\nThis playlist is new, you must add songs to save it to disk!",
                    ssd_,
                )
            return Response(
                _D(
                    "The playlist for this server has been updated to: `%(name)s`%(note)s",
                    ssd_,
                )
                % {"name": opt_url, "note": new_msg},
            )

        if option == "clear":
            if not opt_url and ssd_:
                plname = ssd_.autoplaylist.filename
            else:
                plname = opt_url.lower()
                if not plname.endswith(".txt"):
                    plname += ".txt"
                if not self.playlist_mgr.playlist_exists(plname):
                    raise exceptions.CommandError(
                        "No playlist file exists with the name: `%(playlist)s`",
                        fmt_args={"playlist": plname},
                    )
            pl = self.playlist_mgr.get_playlist(plname)
            await pl.clear_all_tracks(f"Playlist was cleared by user: {author}")
            return Response(
                _D("The playlist `%(playlist)s` has been cleared.", ssd_)
                % {"playlist": plname}
            )

        return None

    @owner_only
    @command_helper(
        desc=_Dd(
            "Generate an invite link that can be used to add this bot to another server."
        ),
        allow_dm=True,
    )
    async def cmd_joinserver(
        self, ssd_: Optional[GuildSpecificData]
    ) -> CommandResponse:
        """
        Generate an oauth invite link for the bot in chat.
        """
        url = await self.generate_invite_link()
        return Response(
            _D("Click here to add me to a discord server:\n%(url)s", ssd_)
            % {"url": url},
        )

    @command_helper(
        desc=_Dd(
            "Toggle karaoke mode on or off. While enabled, only karaoke members may queue songs.\n"
            "Groups with BypassKaraokeMode permission control which members are Karaoke members.\n"
        )
    )
    async def cmd_karaoke(
        self, ssd_: Optional[GuildSpecificData], player: MusicPlayer
    ) -> CommandResponse:
        """
        Toggle the player's karaoke mode.
        """
        player.karaoke_mode = not player.karaoke_mode
        if player.karaoke_mode:
            return Response(_D("\N{OK HAND SIGN} Karaoke mode is now enabled.", ssd_))
        return Response(
            _D("\N{OK HAND SIGN} Karaoke mode is now disabled.", ssd_),
        )

    async def _do_playlist_checks(
        self,
        player: MusicPlayer,
        author: discord.Member,
        result_info: "downloader.YtdlpResponseDict",
    ) -> bool:
        """
        Check if the given `author` has permissions to play the entries
        in `result_info` or not.

        :returns:  True is allowed to continue.
        :raises:  PermissionsError  if permissions deny the playlist.
        """
        num_songs = result_info.playlist_count or result_info.entry_count
        permissions = self.permissions.for_user(author)

        # TODO: correct the language here, since this could be playlist or search results?
        # I have to do extra checks anyways because you can request an arbitrary number of search results
        if not permissions.allow_playlists and num_songs > 1:
            raise exceptions.PermissionsError(
                "You are not allowed to request playlists"
            )

        if (
            permissions.max_playlist_length
            and num_songs > permissions.max_playlist_length
        ):
            raise exceptions.PermissionsError(
                "Playlist has too many entries (%(songs)s but max is %(max)s)",
                fmt_args={"songs": num_songs, "max": permissions.max_playlist_length},
            )

        # This is a little bit weird when it says (x + 0 > y), I might add the other check back in
        if (
            permissions.max_songs
            and player.playlist.count_for_user(author) + num_songs
            > permissions.max_songs
        ):
            raise exceptions.PermissionsError(
                "The playlist entries will exceed your queue limit.\n"
                "There are %(songs)s in the list, and %(queued)s already in queue.\n"
                "The limit is %(max)s for your group.",
                fmt_args={
                    "songs": num_songs,
                    "queued": player.playlist.count_for_user(author),
                    "max": permissions.max_songs,
                },
            )
        return True

    async def _handle_guild_auto_pause(self, player: MusicPlayer, _lc: int = 0) -> None:
        """
        Check the current voice client channel for members and determine
        if the player should be paused automatically.
        This is distinct from Guild availability pausing, which happens
        when Discord or the network has outages.
        """
        if not self.config.auto_pause:
            if player.paused_auto:
                player.paused_auto = False
            return

        if self.network_outage:
            log.debug("Ignoring auto-pause due to network outage.")
            return

        if not player.voice_client or not player.voice_client.channel:
            log.voicedebug(  # type: ignore[attr-defined]
                "MusicPlayer has no VoiceClient or has no channel data, cannot process auto-pause."
            )
            if player.paused_auto:
                player.paused_auto = False
            return

        channel = player.voice_client.channel
        guild = channel.guild

        lock = self.aiolocks[f"auto_pause:{guild.id}"]
        if lock.locked():
            log.debug("Already processing auto-pause, ignoring this event.")
            return

        async with lock:
            if not player.voice_client.is_connected():
                if self.loop:
                    naptime = 3 * (1 + _lc)
                    log.warning(
                        "%sVoiceClient not connected, waiting %s seconds to handle auto-pause in guild:  %s",
                        "[Bug] " if _lc > 12 else "",
                        naptime,
                        player.voice_client.guild,
                    )
                    try:
                        await asyncio.sleep(naptime)
                    except asyncio.CancelledError:
                        log.debug("Auto-pause waiting was cancelled.")
                        return

                    _lc += 1
                    f_player = self.get_player_in(player.voice_client.guild)
                    if player != f_player:
                        log.info(
                            "A new MusicPlayer is being connected, ignoring old auto-pause event."
                        )
                        return

                    if f_player is not None:
                        self.create_task(
                            self._handle_guild_auto_pause(f_player, _lc=_lc),
                            name="MB_HandleGuildAutoPause",
                        )
                return

        is_empty = is_empty_voice_channel(
            channel, include_bots=self.config.bot_exception_ids
        )
        if is_empty and player.is_playing:
            log.info(
                "Playing in an empty voice channel, running auto pause for guild: %s",
                guild,
            )
            player.pause()
            player.paused_auto = True

        elif not is_empty and player.paused_auto:
            log.info("Previously auto paused player is unpausing for guild: %s", guild)
            player.paused_auto = False
            if player.is_paused:
                player.resume()

    async def _do_cmd_unpause_check(
        self,
        player: Optional[MusicPlayer],
        channel: MessageableChannel,
        author: discord.Member,
        message: discord.Message,
    ) -> None:
        """
        Checks for paused player and resumes it while sending a notice.

        This function should not be called from _cmd_play().
        """
        if not self.config.auto_unpause_on_play:
            return

        if not player or not player.voice_client or not player.voice_client.channel:
            return

        if not author.voice or not author.voice.channel:
            return

        # TODO: check this
        if player and player.voice_client and player.voice_client.channel:
            pvc = player.voice_client.channel
            avc = author.voice.channel
            perms = self.permissions.for_user(author)
            ssd = None
            if channel.guild:
                ssd = self.server_data[channel.guild.id]
            if pvc != avc and perms.summonplay:
                await self.cmd_summon(ssd, author.guild, author, message)
                return

            if pvc != avc and not perms.summonplay:
                return

        if player and player.is_paused:
            player.resume()
            await self.safe_send_message(
                channel,
                Response(
                    _D(
                        "Bot was previously paused, resuming playback now.",
                        self.server_data[player.voice_client.channel.guild.id],
                    )
                ),
            )

    @command_helper(
        usage=["{cmd} <URL | SEARCH>"],
        desc=_Dd(
            "Add a song to be played in the queue. If no song is playing or paused, playback will be started.\n"
            "\n"
            "You may supply a URL to a video or audio file or the URL of a service supported by yt-dlp.\n"
            "Playlist links will be extracted into multiple links and added to the queue.\n"
            "If you enter a non-URL, the input will be used as search criteria on YouTube and the first result played.\n"
            "MusicBot also supports Spotify URIs and URLs, but audio is fetched from YouTube regardless.\n"
        ),
    )
    async def cmd_play(
        self,
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
        song_url: str,
    ) -> CommandResponse:
        """
        The default play command logic.
        """
        await self._do_cmd_unpause_check(player, channel, author, message)

        return await self._cmd_play(
            message,
            player,
            channel,
            guild,
            author,
            permissions,
            leftover_args,
            song_url,
            head=False,
        )

    @command_helper(
        usage=["{cmd} [URL]"],
        desc=_Dd(
            "Play command that shuffles playlist entries before adding them to the queue.\n"
        ),
    )
    async def cmd_shuffleplay(
        self,
        ssd_: Optional[GuildSpecificData],
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
        song_url: str,
    ) -> CommandResponse:
        """
        Usage:
            {command_prefix}shuffleplay playlist_link

        Like play command but explicitly shuffles entries before adding them to the queue.
        """
        await self._do_cmd_unpause_check(player, channel, author, message)

        await self._cmd_play(
            message,
            player,
            channel,
            guild,
            author,
            permissions,
            leftover_args,
            song_url,
            head=False,
            shuffle_entries=True,
        )

        return Response(
            _D("Shuffled playlist items into the queue from `%(request)s`", ssd_)
            % {"request": song_url},
        )

    @command_helper(
        usage=["{cmd} <URL | SEARCH>"],
        desc=_Dd(
            "A play command that adds the song as the next to play rather than last.\n"
            "Read help for the play command for information on supported inputs.\n"
        ),
    )
    async def cmd_playnext(
        self,
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
        song_url: str,
    ) -> CommandResponse:
        """
        Add a song directly as the next entry in the queue, if one is playing.
        """
        await self._do_cmd_unpause_check(player, channel, author, message)

        return await self._cmd_play(
            message,
            player,
            channel,
            guild,
            author,
            permissions,
            leftover_args,
            song_url,
            head=True,
        )

    @command_helper(
        usage=["{cmd} <URL | SEARCH>"],
        desc=_Dd(
            "A play command which skips any current song and plays immediately.\n"
            "Read help for the play command for information on supported inputs.\n"
        ),
    )
    async def cmd_playnow(
        self,
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
        song_url: str,
    ) -> CommandResponse:
        """
        Play immediately, skip any playing track.  Don't check skip perms.
        """
        await self._do_cmd_unpause_check(player, channel, author, message)

        # attempt to queue the song, but used the front of the queue and skip current playback.
        return await self._cmd_play(
            message,
            player,
            channel,
            guild,
            author,
            permissions,
            leftover_args,
            song_url,
            head=True,
            skip_playing=True,
        )

    @command_helper(
        usage=["{cmd} <TIME>"],
        desc=_Dd(
            "Restarts the current song at the given time.\n"
            "If time starts with + or - seek will be relative to current playback time.\n"
            "Time should be given in seconds, fractional seconds are accepted.\n"
            "Due to codec specifics in ffmpeg, this may not be accurate.\n"
        ),
    )
    async def cmd_seek(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        player: MusicPlayer,
        leftover_args: List[str],
        seek_time: str = "",
    ) -> CommandResponse:
        """
        Allows for playback seeking functionality in non-streamed entries.
        """
        # TODO: perhaps a means of listing chapters and seeking to them. like `seek ch1` & `seek list`
        if not player or not player.current_entry:
            raise exceptions.CommandError(
                "Cannot use seek if there is nothing playing.",
            )

        if player.current_entry.duration is None:
            raise exceptions.CommandError(
                "Cannot use seek on current track, it has an unknown duration.",
            )

        if not isinstance(
            player.current_entry, (URLPlaylistEntry, LocalFilePlaylistEntry)
        ):
            raise exceptions.CommandError("Seeking is not supported for streams.")

        # take in all potential arguments.
        if leftover_args:
            args = leftover_args
            args.insert(0, seek_time)
            seek_time = " ".join(args)

        if not seek_time:
            raise exceptions.CommandError(
                "Cannot use seek without a time to position playback.",
            )

        relative_seek: int = 0
        f_seek_time: float = 0
        if seek_time.startswith("-"):
            relative_seek = -1
        if seek_time.startswith("+"):
            relative_seek = 1

        if "." in seek_time:
            try:
                p1, p2 = seek_time.rsplit(".", maxsplit=1)
                i_seek_time = format_time_to_seconds(p1)
                f_seek_time = float(f"0.{p2}")
                f_seek_time += i_seek_time
            except (ValueError, TypeError) as e:
                raise exceptions.CommandError(
                    "Could not convert `%(input)s` to a valid time in seconds.",
                    fmt_args={"input": seek_time},
                ) from e
        else:
            f_seek_time = 0.0 + format_time_to_seconds(seek_time)

        if relative_seek != 0:
            f_seek_time = player.progress + (relative_seek * f_seek_time)

        if f_seek_time > player.current_entry.duration or f_seek_time < 0:
            td = format_song_duration(player.current_entry.duration_td)
            prog = format_song_duration(player.progress)
            raise exceptions.CommandError(
                "Cannot seek to `%(input)s` (`%(seconds)s` seconds) in the current track with a length of `%(progress)s / %(total)s`",
                fmt_args={
                    "input": seek_time,
                    "seconds": f"{f_seek_time:.2f}",
                    "progress": prog,
                    "total": td,
                },
            )

        entry = player.current_entry
        entry.set_start_time(f_seek_time)
        player.playlist.insert_entry_at_index(0, entry)

        # handle history playlist updates.
        if (
            self.config.enable_queue_history_global
            or self.config.enable_queue_history_guilds
        ):
            self.server_data[guild.id].current_playing_url = ""

        player.skip()

        return Response(
            _D(
                "Seeking to time `%(input)s` (`%(seconds).2f` seconds) in the current song.",
                ssd_,
            )
            % {
                "input": seek_time,
                "seconds": f_seek_time,
            },
        )

    @command_helper(
        usage=["{cmd} [all | song | playlist | on | off]"],
        desc=_Dd(
            "Toggles playlist or song looping.\n"
            "If no option is provided the current song will be repeated.\n"
            "If no option is provided and the song is already repeating, repeating will be turned off.\n"
        ),
    )
    async def cmd_repeat(
        self, ssd_: Optional[GuildSpecificData], player: MusicPlayer, option: str = ""
    ) -> CommandResponse:
        """
        switch through the various repeat modes.
        """
        # TODO: this command needs TLC.

        option = option.lower() if option else ""

        if not player.current_entry:
            return Response(
                _D(
                    "No songs are currently playing. Play something with a play command.",
                    ssd_,
                )
            )

        if option not in ["all", "playlist", "on", "off", "song", ""]:
            raise exceptions.CommandError(
                "Invalid sub-command. Use the command `help repeat` for usage examples.",
            )

        if option in ["all", "playlist"]:
            player.loopqueue = not player.loopqueue
            if player.loopqueue:
                return Response(_D("Playlist is now repeating.", ssd_))

            return Response(
                _D("Playlist is no longer repeating.", ssd_),
            )

        if option == "song":
            player.repeatsong = not player.repeatsong
            if player.repeatsong:
                return Response(_D("Player will now loop the current song.", ssd_))

            return Response(_D("Player will no longer loop the current song.", ssd_))

        if option == "on":
            if player.repeatsong:
                return Response(_D("Player is already looping a song!", ssd_))

            player.repeatsong = True
            return Response(_D("Player will now loop the current song.", ssd_))

        if option == "off":
            # TODO: This will fail to behave is both are somehow on.
            if player.repeatsong:
                player.repeatsong = False
                return Response(
                    _D("Player will no longer loop the current song.", ssd_)
                )

            if player.loopqueue:
                player.loopqueue = False
                return Response(_D("Playlist is no longer repeating.", ssd_))

            raise exceptions.CommandError("The player is not currently looping.")

        if player.repeatsong:
            player.loopqueue = True
            player.repeatsong = False
            return Response(_D("Playlist is now repeating.", ssd_))

        if player.loopqueue:
            if len(player.playlist.entries) > 0:
                message = _D("Playlist is no longer repeating.", ssd_)
            else:
                message = _D("Song is no longer repeating.", ssd_)
            player.loopqueue = False
        else:
            player.repeatsong = True
            message = _D("Song is now repeating.", ssd_)

        return Response(message)

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} <FROM> <TO>\n"
            + _Dd("    Move song at position FROM to position TO.\n"),
        ],
        # fmt: on
        desc=_Dd(
            "Swap existing songs in the queue using their position numbers.\n"
            "Use the queue command to find track position numbers.\n"
        ),
    )
    async def cmd_move(
        self,
        ssd_: Optional[GuildSpecificData],
        player: MusicPlayer,
        guild: discord.Guild,
        channel: MessageableChannel,
        command: str,
        leftover_args: List[str],
    ) -> CommandResponse:
        """
        Swaps the location of a song within the playlist.
        """
        if not player.current_entry:
            return Response(
                _D(
                    "There are no songs queued. Play something with a play command.",
                    ssd_,
                ),
            )

        indexes = []
        try:
            indexes.append(int(command) - 1)
            indexes.append(int(leftover_args[0]) - 1)
        except (ValueError, IndexError) as e:
            raise exceptions.CommandError("Song positions must be integers!") from e

        for i in indexes:
            if i < 0 or i > len(player.playlist.entries) - 1:
                raise exceptions.CommandError(
                    "You gave a position outside the playlist size!"
                )

        await self.safe_send_message(
            channel,
            Response(
                _D(
                    "Successfully moved song from position %(from)s in queue to position %(to)s!",
                    self.server_data[guild.id],
                )
                % {"from": indexes[0] + 1, "to": indexes[1] + 1},
            ),
        )

        song = player.playlist.delete_entry_at_index(indexes[0])

        player.playlist.insert_entry_at_index(indexes[1], song)
        return None

    # Not a command :)
    async def _cmd_play_compound_link(
        self,
        ssd_: Optional[GuildSpecificData],
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
        song_url: str,
        head: bool,
    ) -> None:
        """
        Helper function to check for playlist IDs embedded in video links.
        If a "compound" URL is detected, ask the user if they want the
        associated playlist to be queued as well.
        """
        # TODO: maybe add config to auto yes or no and bypass this.

        async def _prompt_for_playing(
            prompt: str, next_url: str, ignore_vid: str = ""
        ) -> None:
            msg = await self.safe_send_message(
                channel, Response(prompt, delete_after=self.config.delete_delay_long)
            )
            if not msg:
                log.warning(
                    "Could not prompt for playlist playback, no message to add reactions to."
                )
                return

            for r in [EMOJI_CHECK_MARK_BUTTON, EMOJI_CROSS_MARK_BUTTON]:
                await msg.add_reaction(r)

            def _check_react(reaction: discord.Reaction, user: discord.Member) -> bool:
                return msg == reaction.message and author == user

            try:
                reaction, _user = await self.wait_for(
                    "reaction_add", timeout=60, check=_check_react
                )
                if reaction.emoji == EMOJI_CHECK_MARK_BUTTON:
                    await self._cmd_play(
                        message,
                        player,
                        channel,
                        guild,
                        author,
                        permissions,
                        leftover_args,
                        next_url,
                        head,
                        ignore_video_id=ignore_vid,
                    )
                    await self.safe_delete_message(msg)
                elif reaction.emoji == EMOJI_CROSS_MARK_BUTTON:
                    await self.safe_delete_message(msg)
            except asyncio.TimeoutError:
                await self.safe_delete_message(msg)

        # Check for playlist in youtube watch link.
        # https://youtu.be/VID?list=PLID
        # https://www.youtube.com/watch?v=VID&list=PLID
        playlist_regex = re.compile(
            r"(?:youtube.com/watch\?v=|youtu\.be/)([^?&]{6,})[&?]{1}(list=PL[^&]+)",
            re.I | re.X,
        )
        matches = playlist_regex.search(song_url)
        if matches:
            pl_url = "https://www.youtube.com/playlist?" + matches.group(2)
            ignore_vid = matches.group(1)
            self.create_task(
                _prompt_for_playing(
                    _D(
                        "This link contains a Playlist ID:\n"
                        "`%(url)s`\n\nDo you want to queue the playlist too?",
                        ssd_,
                    )
                    % {"url": song_url},
                    pl_url,
                    ignore_vid,
                )
            )

    # Not a command. :)
    async def _cmd_play(
        self,
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
        song_url: str,
        head: bool,
        shuffle_entries: bool = False,
        ignore_video_id: str = "",
        skip_playing: bool = False,
    ) -> CommandResponse:
        """
        This function handles actually adding any given URL or song subject to
        the player playlist if extraction was successful and various checks pass.

        :param: head:  Toggle adding the song(s) to the front of the queue, not the end.
        :param: shuffle_entries:  Shuffle entries before adding them to the queue.
        :param: ignore_video_id:  Ignores a video in a playlist if it has this ID.
        :param: skip_playing:  Skip current playback if a new entry is added.
        """
        ssd_ = self.server_data[guild.id]
        await channel.typing()

        if not self.config.enable_local_media and song_url.lower().startswith(
            "file://"
        ):
            raise exceptions.CommandError(
                "Local media playback is not enabled.",
            )

        # Validate song_url is actually a URL, or otherwise a search string.
        valid_song_url = self.downloader.get_url_or_none(song_url)
        if valid_song_url:
            song_url = valid_song_url
            self._do_song_blocklist_check(song_url)

            # Handle if the link has a playlist ID in addition to a video ID.
            await self._cmd_play_compound_link(
                ssd_,
                message,
                player,
                channel,
                guild,
                author,
                permissions,
                leftover_args,
                song_url,
                head,
            )

        if (
            not valid_song_url
            and leftover_args
            and not (
                self.config.enable_local_media
                and song_url.lower().startswith("file://")
            )
        ):
            # treat all arguments as a search string.
            song_url = " ".join([song_url, *leftover_args])
            leftover_args = []  # prevent issues later.
            self._do_song_blocklist_check(song_url)

        # Validate spotify links are supported before we try them.
        if "open.spotify.com" in song_url.lower():
            if self.config.spotify_enabled:
                if not Spotify.is_url_supported(song_url):
                    raise exceptions.CommandError(
                        "Spotify URL is invalid or not currently supported."
                    )
            else:
                raise exceptions.CommandError(
                    "Detected a Spotify URL, but Spotify is not enabled."
                )

        # This lock prevent spamming play commands to add entries that exceeds time limit/ maximum song limit
        async with self.aiolocks[_func_() + ":" + str(author.id)]:
            if (
                permissions.max_songs
                and player.playlist.count_for_user(author) >= permissions.max_songs
            ):
                raise exceptions.PermissionsError(
                    "You have reached your enqueued song limit (%(max)s)",
                    fmt_args={"max": permissions.max_songs},
                )

            if player.karaoke_mode and not permissions.bypass_karaoke_mode:
                raise exceptions.PermissionsError(
                    "Karaoke mode is enabled, please try again when its disabled!",
                )

            # Get processed info from ytdlp
            info = None
            try:
                info = await self.downloader.extract_info(
                    song_url, download=False, process=True
                )
            except Exception as e:
                # TODO: i18n for translated exceptions.
                info = None
                log.exception("Issue with extract_info(): ")
                if isinstance(e, exceptions.MusicbotException):
                    raise
                raise exceptions.CommandError(
                    "Failed to extract info due to error:\n%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

            if not info:
                raise exceptions.CommandError(
                    "That video cannot be played. Try using the stream command.",
                )

            # ensure the extractor has been allowed via permissions.
            permissions.can_use_extractor(info.extractor)

            # if the result has "entries" but it's empty, it might be a failed search.
            if "entries" in info and not info.entry_count:
                if info.extractor.startswith("youtube:search"):
                    # TOOD: UI, i18n stuff
                    raise exceptions.CommandError(
                        "YouTube search returned no results for:  %(url)s",
                        fmt_args={"url": song_url},
                    )

            # If the result has usable entries, we assume it is a playlist
            listlen = 1
            track_title = ""
            if info.has_entries:
                await self._do_playlist_checks(player, author, info)

                num_songs = info.playlist_count or info.entry_count

                if shuffle_entries:
                    random.shuffle(info["entries"])

                # TODO: I can create an event emitter object instead, add event functions, and every play list might be asyncified
                # Also have a "verify_entry" hook with the entry as an arg and returns the entry if its ok
                start_time = time.time()
                entry_list, position = await player.playlist.import_from_info(
                    info,
                    channel=channel,
                    author=author,
                    head=head,
                    ignore_video_id=ignore_video_id,
                )

                time_taken = time.time() - start_time
                listlen = len(entry_list)

                log.info(
                    "Processed %(number)d of %(total)d songs in %(time).3f seconds at %(time_per).2f s/song",
                    {
                        "number": listlen,
                        "total": num_songs,
                        "time": time_taken,
                        "time_per": time_taken / listlen if listlen else 1,
                    },
                )

                if not entry_list:
                    raise exceptions.CommandError(
                        "No songs were added, all songs were over max duration (%(max)s seconds)",
                        fmt_args={"max": permissions.max_song_length},
                    )

                reply_text = _D(
                    "Enqueued **%(number)s** songs to be played.\n"
                    "Position in queue: %(position)s",
                    ssd_,
                )

            # If it's an entry
            else:
                # youtube:playlist extractor but it's actually an entry
                # ^ wish I had a URL for this one.
                if info.get("extractor", "").startswith("youtube:playlist"):
                    log.noise(  # type: ignore[attr-defined]
                        "Extracted an entry with 'youtube:playlist' as extractor key"
                    )

                # Check the block list again, with the info this time.
                self._do_song_blocklist_check(info.url)
                self._do_song_blocklist_check(info.title)

                if (
                    permissions.max_song_length
                    and info.duration_td.seconds > permissions.max_song_length
                ):
                    raise exceptions.PermissionsError(
                        "Song duration exceeds limit (%(length)s > %(max)s)",
                        fmt_args={
                            "length": info.duration,
                            "max": permissions.max_song_length,
                        },
                    )

                entry, position = await player.playlist.add_entry_from_info(
                    info, channel=channel, author=author, head=head
                )

                reply_text = _D(
                    "Enqueued `%(track)s` to be played.\n"
                    "Position in queue: %(position)s",
                    ssd_,
                )
                track_title = _D(entry.title, ssd_)

            log.debug("Added song(s) at position %s", position)
            if position == 1 and player.is_stopped:
                pos_str = _D("Playing next!", ssd_)
                player.play()

            # shift the playing track to the end of queue and skip current playback.
            elif skip_playing and player.is_playing and player.current_entry:
                player.playlist.entries.append(player.current_entry)

                # handle history playlist updates.
                if (
                    self.config.enable_queue_history_global
                    or self.config.enable_queue_history_guilds
                ):
                    self.server_data[guild.id].current_playing_url = ""

                player.skip()
                pos_str = _D("Playing next!", ssd_)

            else:
                try:
                    time_until = await player.playlist.estimate_time_until(
                        position, player
                    )
                    pos_str = _D(
                        "%(position)s - estimated time until playing: `%(eta)s`",
                        ssd_,
                    ) % {
                        "position": position,
                        "eta": format_song_duration(time_until),
                    }
                except exceptions.InvalidDataError:
                    pos_str = _D(
                        "%(position)s - cannot estimate time until playing.",
                        ssd_,
                    ) % {"position": position}
                    log.warning(
                        "Cannot estimate time until playing for position: %d", position
                    )

        reply_text %= {
            "number": listlen,
            "track": track_title,
            "position": pos_str,
        }

        return Response(reply_text)

    @command_helper(
        usage=["{cmd} <URL>"],
        desc=_Dd(
            "Add a media URL to the queue as a Stream.\n"
            "The URL may be actual streaming media, like Twitch, Youtube, or a shoutcast like service.\n"
            "You can also use non-streamed media to play it without downloading it.\n"
            "Note: FFmpeg may drop the stream randomly or if connection hiccups happen.\n"
        ),
    )
    async def cmd_stream(
        self,
        ssd_: Optional[GuildSpecificData],
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        author: discord.Member,
        permissions: PermissionGroup,
        message: discord.Message,
        song_url: str,
    ) -> CommandResponse:
        """
        Tries to add media to the queue as a stream entry type.
        """

        await self._do_cmd_unpause_check(player, channel, author, message)

        # TODO: make sure these permissions checks are used in all play* functions.
        if (
            permissions.max_songs
            and player.playlist.count_for_user(author) >= permissions.max_songs
        ):
            raise exceptions.PermissionsError(
                "You have reached your enqueued song limit (%(max)s)",
                fmt_args={"max": permissions.max_songs},
            )

        if player.karaoke_mode and not permissions.bypass_karaoke_mode:
            raise exceptions.PermissionsError(
                "Karaoke mode is enabled, please try again when its disabled!",
            )

        async with channel.typing():
            # TODO: find more streams to test.
            # NOTE: this will return a URL if one was given but ytdl doesn't support it.
            try:
                info = await self.downloader.extract_info(
                    song_url, download=False, process=True, as_stream=True
                )
            # TODO: i18n handle translation of exceptions
            except Exception as e:
                log.exception(
                    "Failed to get info from the stream request: %s", song_url
                )
                raise exceptions.CommandError(
                    "Failed to extract info due to error:\n%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

            if info.has_entries:
                raise exceptions.CommandError(
                    "Streaming playlists is not yet supported.",
                )
                # TODO: could process these and force them to be stream entries...

            self._do_song_blocklist_check(info.url)
            # if its a "forced stream" this would be a waste.
            if info.url != info.title:
                self._do_song_blocklist_check(info.title)

            await player.playlist.add_stream_from_info(
                info, channel=channel, author=author, head=False
            )

            if player.is_stopped:
                player.play()

        return Response(
            _D("Now streaming track `%(track)s`", ssd_) % {"track": info.title},
        )

    # TODO: cmd_streamnext maybe

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} [SERVICE] [NUMBER] <QUERY>\n"
            + _Dd("    Search with service for a number of results with the search query.\n"),

            "{cmd} [NUMBER] \"<QUERY>\"\n"
            + _Dd(
                "    Search YouTube for query but get a custom number of results.\n"
                "    Note: the double-quotes are required in this case.\n"
            ),
        ],
        # fmt: on
        desc=_Dd(
            "Search a supported service and select from results to add to queue.\n"
            "Service and number arguments can be omitted, default number is 3 results.\n"
            "Select from these services:\n"
            "- yt, youtube (default)\n"
            "- sc, soundcloud\n"
            "- yh, yahoo\n"
        ),
    )
    async def cmd_search(
        self,
        ssd_: Optional[GuildSpecificData],
        message: discord.Message,
        player: MusicPlayer,
        channel: GuildMessageableChannels,
        guild: discord.Guild,
        author: discord.Member,
        permissions: PermissionGroup,
        leftover_args: List[str],
    ) -> CommandResponse:
        """
        Facilitate search with yt-dlp and some select services.
        This starts an interactive message where reactions are used to navigate
        and select from the results.  Only the calling member may react.
        """

        if (
            permissions.max_songs
            and player.playlist.count_for_user(author) > permissions.max_songs
        ):
            raise exceptions.PermissionsError(
                "You have reached your playlist item limit (%(max)s)",
                fmt_args={"max": permissions.max_songs},
            )

        if player.karaoke_mode and not permissions.bypass_karaoke_mode:
            raise exceptions.PermissionsError(
                "Karaoke mode is enabled, please try again when its disabled!",
            )

        def argcheck() -> None:
            if not leftover_args:
                raise exceptions.CommandError(
                    "Please specify a search query.  Use `help search` for more information.",
                )

        argcheck()

        service = "youtube"
        items_requested = self.config.defaultsearchresults
        max_items = permissions.max_search_items
        services = {
            "youtube": "ytsearch",
            "soundcloud": "scsearch",
            "yahoo": "yvsearch",
            "yt": "ytsearch",
            "sc": "scsearch",
            "yh": "yvsearch",
        }

        # handle optional [SERVICE] arg
        if leftover_args[0] in services:
            service = leftover_args.pop(0)
            argcheck()

        # handle optional [RESULTS]
        if leftover_args[0].isdigit():
            items_requested = int(leftover_args.pop(0))
            argcheck()

            if items_requested > max_items:
                raise exceptions.CommandError(
                    "You cannot search for more than %(max)s videos",
                    fmt_args={"max": max_items},
                )

        # Look jake, if you see this and go "what the fuck are you doing"
        # and have a better idea on how to do this, I'd be delighted to know.
        # I don't want to just do ' '.join(leftover_args).strip("\"'")
        # Because that eats both quotes if they're there
        # where I only want to eat the outermost ones
        if leftover_args[0][0] in "'\"":
            lchar = leftover_args[0][0]
            leftover_args[0] = leftover_args[0].lstrip(lchar)
            leftover_args[-1] = leftover_args[-1].rstrip(lchar)

        ssd = self.server_data[guild.id]
        srvc = services[service]
        args_str = " ".join(leftover_args)
        search_query = f"{srvc}{items_requested}:{args_str}"

        self._do_song_blocklist_check(args_str)

        search_msg = await self.safe_send_message(
            channel,
            Response(_D("Searching for videos...", ssd)),
        )
        await channel.typing()

        try:  # pylint: disable=no-else-return
            info = await self.downloader.extract_info(
                search_query, download=False, process=True
            )

        except (
            exceptions.ExtractionError,
            exceptions.SpotifyError,
            youtube_dl.utils.YoutubeDLError,
            youtube_dl.networking.exceptions.RequestError,
        ) as e:
            if search_msg:
                error = str(e)
                if isinstance(e, exceptions.MusicbotException):
                    error = _D(e.message, ssd_) % e.fmt_args
                await self.safe_edit_message(
                    search_msg,
                    ErrorResponse(
                        _D("Search failed due to an error: %(error)s", ssd_)
                        % {"error": error},
                    ),
                    send_if_fail=True,
                )
            return None

        else:
            if search_msg:
                await self.safe_delete_message(search_msg)

        if not info:
            return Response(_D("No videos found.", ssd_))

        entries = info.get_entries_objects()

        # Decide if the list approach or the reaction approach should be used
        if self.config.searchlist:
            result_message_array = []

            content = Response(
                _D("To select a song, type the corresponding number.", ssd_),
                title=_D("Search results from %(service)s:", ssd_)
                % {"service": service},
            )

            for entry in entries:
                # This formats the results and adds it to an array
                # format_song_duration removes the hour section
                # if the song is shorter than an hour
                result_message_array.append(
                    _D("**%(index)s**. **%(track)s** | %(length)s", ssd_)
                    % {
                        "index": entries.index(entry) + 1,
                        "track": entry["title"],
                        "length": format_song_duration(entry.duration_td),
                    },
                )
            # This combines the formatted result strings into one list.
            result_string = "\n".join(str(result) for result in result_message_array)
            result_string += _D("\n**0**. Cancel", ssd_)

            # Add the result entries to the embedded message and send it to the channel
            content.add_field(
                name=_D("Pick a song", ssd_),
                value=result_string,
                inline=False,
            )
            result_message = await self.safe_send_message(channel, content)

            # Check to verify that received message is valid.
            def check(reply: discord.Message) -> bool:
                return (
                    reply.channel.id == channel.id
                    and reply.author == message.author
                    and reply.content.isdigit()
                    and -1 <= int(reply.content) - 1 <= info.entry_count
                )

            # Wait for a response from the author.
            try:
                choice = await self.wait_for(
                    "message",
                    timeout=self.config.delete_delay_long,
                    check=check,
                )
            except asyncio.TimeoutError:
                if result_message:
                    await self.safe_delete_message(result_message)
                return None

            if choice.content == "0":
                # Choice 0 will cancel the search
                if self.config.delete_invoking:
                    await self.safe_delete_message(choice)
                if result_message:
                    await self.safe_delete_message(result_message)
            else:
                # Here we have a valid choice lets queue it.
                if self.config.delete_invoking:
                    await self.safe_delete_message(choice)
                if result_message:
                    await self.safe_delete_message(result_message)
                await self.cmd_play(
                    message,
                    player,
                    channel,
                    guild,
                    author,
                    permissions,
                    [],
                    entries[int(choice.content) - 1]["url"],
                )

                return Response(
                    _D("Added song [%(track)s](%(url)s) to the queue.", ssd_)
                    % {
                        "track": entries[int(choice.content) - 1]["title"],
                        "url": entries[int(choice.content) - 1]["url"],
                    },
                )
        else:
            # patch for loop-defined cell variable.
            res_msg_ids = []
            # Original code
            for entry in entries:
                result_message = await self.safe_send_message(
                    channel,
                    Response(
                        _D("Result %(number)s of %(total)s: %(url)s", ssd)
                        % {
                            "number": entries.index(entry) + 1,
                            "total": info.entry_count,
                            "url": entry["url"],
                        },
                    ),
                )
                if not result_message:
                    continue

                res_msg_ids.append(result_message.id)

                def check_react(
                    reaction: discord.Reaction, user: discord.Member
                ) -> bool:
                    return (
                        user == message.author and reaction.message.id in res_msg_ids
                    )  # why can't these objs be compared directly?

                reactions = [
                    EMOJI_CHECK_MARK_BUTTON,
                    EMOJI_CROSS_MARK_BUTTON,
                    EMOJI_STOP_SIGN,
                ]
                for r in reactions:
                    await result_message.add_reaction(r)

                try:
                    reaction, _user = await self.wait_for(
                        "reaction_add", timeout=60.0, check=check_react
                    )
                except asyncio.TimeoutError:
                    await self.safe_delete_message(result_message)
                    return None

                if str(reaction.emoji) == EMOJI_CHECK_MARK_BUTTON:  # check
                    # play the next and respond, stop the search entry loop.
                    await self.safe_delete_message(result_message)
                    await self.cmd_play(
                        message,
                        player,
                        channel,
                        guild,
                        author,
                        permissions,
                        [],
                        entry["url"],
                    )
                    return Response(
                        _D("Alright, coming right up!", ssd_),
                    )

                if str(reaction.emoji) == EMOJI_CROSS_MARK_BUTTON:  # cross
                    # delete last result and move on to next
                    await self.safe_delete_message(result_message)
                else:  # stop
                    # delete last result and stop showing results.
                    await self.safe_delete_message(result_message)
                    break
        return None

    @command_helper(desc=_Dd("Show information on what is currently playing."))
    async def cmd_np(
        self,
        ssd_: Optional[GuildSpecificData],
        player: MusicPlayer,
        channel: MessageableChannel,
        guild: discord.Guild,
    ) -> CommandResponse:
        """
        Displays data on the current track if any.
        """
        # TODO: this may still need more tweaks for better i18n support.
        # Something to address the fragmented nature of strings in embeds.
        if player.current_entry:
            last_np_msg = self.server_data[guild.id].last_np_msg
            if last_np_msg:
                await self.safe_delete_message(last_np_msg)
                self.server_data[guild.id].last_np_msg = None

            song_progress = format_song_duration(player.progress)
            song_total = (
                format_song_duration(player.current_entry.duration_td)
                if player.current_entry.duration is not None
                else "(no duration data)"
            )

            streaming = isinstance(player.current_entry, StreamPlaylistEntry)
            prog_str = (
                "`[{progress}]`" if streaming else "`[{progress}/{total}]`"
            ).format(progress=song_progress, total=song_total)
            prog_bar_str = ""

            # percentage shows how much of the current song has already been played
            percentage = 0.0
            if (
                player.current_entry.duration
                and player.current_entry.duration_td.total_seconds() > 0
            ):
                percentage = (
                    player.progress / player.current_entry.duration_td.total_seconds()
                )

            # create the actual bar
            progress_bar_length = 30
            for i in range(progress_bar_length):
                if percentage < 1 / progress_bar_length * i:
                    prog_bar_str += "□"
                else:
                    prog_bar_str += "■"

            entry = player.current_entry
            entry_author = player.current_entry.author
            added_by = _D("[autoplaylist]", ssd_)
            if entry_author:
                added_by = entry_author.name

            content = Response("", title=_D("Now playing", ssd_))
            content.add_field(
                name=(
                    _D("Currently streaming:", ssd_)
                    if streaming
                    else _D("Currently playing:", ssd_)
                ),
                value=_D(entry.title, ssd_),
                inline=False,
            )
            content.add_field(
                name=_D("Added By:", ssd_),
                value=_D("`%(user)s`", ssd_) % {"user": added_by},
                inline=False,
            )
            content.add_field(
                name=_D("Progress:", ssd_),
                value=f"{prog_str}\n{prog_bar_str}\n\n",
                inline=False,
            )
            if len(entry.url) <= 1024:
                content.add_field(name="URL:", value=entry.url, inline=False)
            if entry.thumbnail_url:
                content.set_image(url=entry.thumbnail_url)
            else:
                log.warning("No thumbnail set for entry with URL: %s", entry.url)

            self.server_data[guild.id].last_np_msg = await self.safe_send_message(
                channel,
                content,
            )
            return None

        return Response(
            _D("There are no songs queued! Queue something with a play command.", ssd_)
        )

    @command_helper(desc=_Dd("Tell MusicBot to join the channel you're in."))
    async def cmd_summon(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        author: discord.Member,
        message: discord.Message,
    ) -> CommandResponse:
        """
        With a lock, join the caller's voice channel.
        This method will create a MusicPlayer and VoiceClient pair if needed.
        """

        lock_key = f"summon:{guild.id}"

        if self.aiolocks[lock_key].locked():
            log.debug("Waiting for summon lock: %s", lock_key)

        async with self.aiolocks[lock_key]:
            log.debug("Summon lock acquired for: %s", lock_key)

            if not author.voice or not author.voice.channel:
                raise exceptions.CommandError(
                    "You are not connected to voice. Try joining a voice channel!",
                )

            # either move an existing VoiceClient / MusicPlayer pair or make them.
            player = self.get_player_in(guild)
            if player and player.voice_client and guild == author.voice.channel.guild:
                # NOTE:  .move_to() does not support setting self-deafen flag,
                # nor respect flags set in initial connect call.
                # TODO: keep tabs on how this changes in later versions of d.py.
                # await player.voice_client.move_to(author.voice.channel)
                await guild.change_voice_state(
                    channel=author.voice.channel,
                    self_deaf=self.config.self_deafen,
                )
            else:
                player = await self.get_player(
                    author.voice.channel,
                    create=True,
                    deserialize=self.config.persistent_queue,
                )

                if player.is_stopped:
                    player.play()

            log.info(
                "Joining %(guild)s/%(channel)s",
                {
                    "guild": author.voice.channel.guild.name,
                    "channel": author.voice.channel.name,
                },
            )

            self.server_data[guild.id].last_np_msg = message

            return Response(
                _D("Connected to `%(channel)s`", ssd_)
                % {"channel": author.voice.channel},
            )

    @command_helper(
        desc=_Dd(
            "Makes MusicBot follow a user when they change channels in a server.\n"
        )
    )
    async def cmd_follow(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        author: discord.Member,
        user_mentions: UserMentions,
    ) -> CommandResponse:
        """
        Bind a user to be followed by MusicBot between channels in a server.
        """
        # If MusicBot is already following a user, either change user or un-follow.
        followed_user = self.server_data[guild.id].follow_user
        if followed_user is not None:
            # Un-follow current user.
            if followed_user.id == author.id:
                # TODO:  maybe check the current channel for users and decide if
                # we should automatically move back to guilds auto_join_channel.
                self.server_data[guild.id].follow_user = None
                return Response(
                    _D(
                        "No longer following user `%(user)s`",
                        ssd_,
                    )
                    % {"user": author.name}
                )

            # Change to following a new user.
            self.server_data[guild.id].follow_user = author
            return Response(
                _D(
                    "Now following user `%(user)s` between voice channels.",
                    ssd_,
                )
                % {"user": author.name}
            )

        # Follow the invoking user.
        # If owner mentioned a user, bind to the mentioned user instead.
        bind_to_member = author
        if author.id == self.config.owner_id and user_mentions:
            m = user_mentions.pop(0)
            if not isinstance(m, discord.Member):
                raise exceptions.CommandError(
                    "MusicBot cannot follow a user that is not a member of the server.",
                )
            bind_to_member = m

        self.server_data[guild.id].follow_user = bind_to_member
        return Response(
            _D(
                "Will follow user `%(user)s` between voice channels.",
                ssd_,
            )
            % {"user": bind_to_member.name}
        )

    @command_helper(desc=_Dd("Pause playback if a track is currently playing."))
    async def cmd_pause(
        self, ssd_: Optional[GuildSpecificData], player: MusicPlayer
    ) -> CommandResponse:
        """
        Pauses playback of the current song.
        """

        if player.is_playing:
            player.pause()
            return Response(
                _D("Paused music in `%(channel)s`", ssd_)
                % {"channel": player.voice_client.channel},
            )

        raise exceptions.CommandError("Player is not playing.")

    @command_helper(desc=_Dd("Resumes playback if the player was previously paused."))
    async def cmd_resume(
        self, ssd_: Optional[GuildSpecificData], player: MusicPlayer
    ) -> CommandResponse:
        """
        Resume a paused player.
        """

        if player.is_paused:
            player.resume()
            return Response(
                _D("Resumed music in `%(channel)s`", ssd_)
                % {"channel": player.voice_client.channel.name},
            )

        if player.is_stopped and player.playlist:
            player.play()
            return Response(_D("Resumed music queue", ssd_))

        return ErrorResponse(_D("Player is not paused.", ssd_))

    @command_helper(desc=_Dd("Shuffle all current tracks in the queue."))
    async def cmd_shuffle(
        self,
        ssd_: Optional[GuildSpecificData],
        channel: MessageableChannel,
        player: MusicPlayer,
    ) -> CommandResponse:
        """
        Shuffle all tracks in the player queue for the calling guild.
        """

        player.playlist.shuffle()

        cards = [
            "\N{BLACK SPADE SUIT}",
            "\N{BLACK CLUB SUIT}",
            "\N{BLACK HEART SUIT}",
            "\N{BLACK DIAMOND SUIT}",
        ]
        random.shuffle(cards)

        hand = await self.safe_send_message(
            channel, Response(" ".join(cards), force_text=True)
        )
        await asyncio.sleep(0.6)

        if hand:
            for _ in range(4):
                random.shuffle(cards)
                await self.safe_edit_message(
                    hand, Response(" ".join(cards), force_text=True)
                )
                await asyncio.sleep(0.6)

            await self.safe_delete_message(hand)
        return Response(_D("Shuffled all songs in the queue.", ssd_))

    @command_helper(desc=_Dd("Removes all songs currently in the queue."))
    async def cmd_clear(
        self,
        ssd_: Optional[GuildSpecificData],
        _player: MusicPlayer,
        guild: discord.Guild,
    ) -> CommandResponse:
        """
        Clears the playlist but does not skip current playing track.
        If no player is available the queue file will be removed if it exists.
        """

        # Ensure player is not none and that it's not empty
        if _player and len(_player.playlist) < 1:
            raise exceptions.CommandError(
                "There is nothing currently playing. Play something with a play command."
            )

        # Try to gracefully clear the guild queue if we're not in a vc.
        if not _player:
            queue_path = self.config.data_path.joinpath(
                f"{guild.id}/{DATA_GUILD_FILE_QUEUE}"
            )
            try:
                queue_path.unlink()
            except FileNotFoundError:
                pass  # Silently ignore if file doesn't exist.
            except PermissionError:
                log.error(
                    "Missing permissions to delete queue file for %(guild)s(%(id)s) at: %(path)s",
                    {"guild": guild.name, "id": guild.id, "path": queue_path},
                )
            except OSError:
                log.exception(
                    "OS level error while trying to delete queue file: %(path)s",
                    {"path": queue_path},
                )
        else:
            _player.playlist.clear()  # Clear playlist from vc

        return Response(_D("Cleared all songs from the queue.", ssd_))

    @command_helper(
        usage=["{cmd} [POSITION]"],
        desc=_Dd(
            "Remove a song from the queue, optionally at the given queue position.\n"
            "If the position is omitted, the song at the end of the queue is removed.\n"
            "Use the queue command to find position number of your track.\n"
            "However, positions of all songs are changed when a new song starts playing.\n"
        ),
    )
    async def cmd_remove(
        self,
        ssd_: Optional[GuildSpecificData],
        user_mentions: UserMentions,
        author: discord.Member,
        permissions: PermissionGroup,
        player: MusicPlayer,
        index: str = "",
    ) -> CommandResponse:
        """
        Command to remove entries from the player queue using relative IDs or LIFO method.
        """

        if not player.playlist.entries:
            raise exceptions.CommandError("Nothing in the queue to remove!")

        if user_mentions:
            for user in user_mentions:
                if permissions.remove or author == user:
                    try:
                        entry_indexes = [
                            e for e in player.playlist.entries if e.author == user
                        ]
                        for entry in entry_indexes:
                            player.playlist.entries.remove(entry)
                        entry_text = f"{len(entry_indexes)} item"
                        if len(entry_indexes) > 1:
                            entry_text += "s"
                        return Response(
                            _D("Removed `%(track)s` added by `%(user)s`", ssd_)
                            % {"track": entry_text, "user": user.name},
                        )

                    except ValueError as e:
                        raise exceptions.CommandError(
                            "Nothing found in the queue from user `%(user)s`",
                            fmt_args={"user": user.name},
                        ) from e

                raise exceptions.PermissionsError(
                    "You do not have the permission to remove that entry from the queue.\n"
                    "You must be the one who queued it or have instant skip permissions.",
                )

        if not index:
            idx = len(player.playlist.entries)

        try:
            idx = int(index)
        except (TypeError, ValueError) as e:
            raise exceptions.CommandError(
                "Invalid entry number. Use the queue command to find queue positions.",
            ) from e

        if idx > len(player.playlist.entries):
            raise exceptions.CommandError(
                "Invalid entry number. Use the queue command to find queue positions.",
            )

        if (
            permissions.remove
            or author == player.playlist.get_entry_at_index(idx - 1).author
        ):
            entry = player.playlist.delete_entry_at_index((idx - 1))
            if entry.channel and entry.author:
                return Response(
                    _D("Removed entry `%(track)s` added by `%(user)s`", ssd_)
                    % {"track": _D(entry.title, ssd_), "user": entry.author.name},
                )

            return Response(
                _D("Removed entry `%(track)s`", ssd_)
                % {"track": _D(entry.title, ssd_)},
            )

        raise exceptions.PermissionsError(
            "You do not have the permission to remove that entry from the queue.\n"
            "You must be the one who queued it or have instant skip permissions.",
        )

    @command_helper(
        usage=["{cmd} [force | f]"],
        desc=_Dd(
            "Skip or vote to skip the current playing song.\n"
            "Members with InstaSkip permission may use force parameter to bypass voting.\n"
            "If LegacySkip option is enabled, the force parameter can be ignored.\n"
        ),
    )
    async def cmd_skip(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        player: MusicPlayer,
        author: discord.Member,
        message: discord.Message,
        permissions: PermissionGroup,
        voice_channel: Optional[VoiceableChannel],
        param: str = "",
    ) -> CommandResponse:
        """
        Implements the multi-featured skip logic for skip voting or forced skiping.
        Several options and a permission change how this command works.
        InstaSkip permission will allow force, which is not required if LegacySkip option is enabled.
        SkipRatio and SkipsRequired determine how voting is counted and if voting is enabled.
        """

        if player.is_stopped:
            raise exceptions.CommandError("Can't skip! The player is not playing!")

        if not player.current_entry:
            next_entry = player.playlist.peek()
            if next_entry:
                if next_entry.is_downloading:
                    return Response(
                        _D(
                            "The next song `%(track)s` is downloading, please wait.",
                            ssd_,
                        )
                        % {"track": _D(next_entry.title, ssd_)},
                    )

                if next_entry.is_downloaded:
                    return Response(
                        _D("The next song will be played shortly. Please wait.", ssd_)
                    )

                return Response(
                    _D(
                        "Something odd is happening.\n"
                        "You might want to restart the bot if it doesn't start working.",
                        ssd_,
                    )
                )
            return Response(
                _D(
                    "Something strange is happening.\n"
                    "You might want to restart the bot if it doesn't start working.",
                    ssd_,
                )
            )

        current_entry = player.current_entry
        entry_author = current_entry.author
        entry_author_id = 0
        if entry_author:
            entry_author_id = entry_author.id

        permission_force_skip = permissions.instaskip or (
            self.config.allow_author_skip and author.id == entry_author_id
        )
        force_skip = param.lower() in ["force", "f"]

        if permission_force_skip and (force_skip or self.config.legacy_skip):
            if (
                not permission_force_skip
                and not permissions.skip_looped
                and player.repeatsong
            ):
                raise exceptions.PermissionsError(
                    "You do not have permission to force skip a looped song.",
                )

            # handle history playlist updates.
            if (
                self.config.enable_queue_history_global
                or self.config.enable_queue_history_guilds
            ):
                self.server_data[guild.id].current_playing_url = ""

            if player.repeatsong:
                player.repeatsong = False
            player.skip()
            return Response(
                _D("Force skipped `%(track)s`.", ssd_)
                % {"track": _D(current_entry.title, ssd_)},
            )

        if not permission_force_skip and force_skip:
            raise exceptions.PermissionsError(
                "You do not have permission to force skip."
            )

        # get the number of users in the channel who are not deaf, exclude bots with exceptions.
        num_voice = count_members_in_voice(
            voice_channel,
            # make sure we include bot exceptions.
            include_bots=self.config.bot_exception_ids,
        )
        # If all users are deaf, avoid ZeroDivisionError
        if num_voice == 0:
            num_voice = 1

        # add the current skipper id so we can count it.
        player.skip_state.add_skipper(author.id, message)
        # count all members who are in skippers set.
        num_skips = count_members_in_voice(
            voice_channel,
            # This will exclude all other members in the channel who have not skipped.
            include_only=player.skip_state.skippers,
            # If a bot has skipped, this allows the exceptions to be counted.
            include_bots=self.config.bot_exception_ids,
        )

        skips_remaining = (
            min(
                self.config.skips_required,
                math.ceil(
                    self.config.skip_ratio_required / (1 / num_voice)
                ),  # Number of skips from config ratio
            )
            - num_skips
        )

        if skips_remaining <= 0:
            if not permissions.skip_looped and player.repeatsong:
                raise exceptions.PermissionsError(
                    "You do not have permission to skip a looped song.",
                )

            if player.repeatsong:
                player.repeatsong = False

            # handle history playlist updates.
            if (
                self.config.enable_queue_history_global
                or self.config.enable_queue_history_guilds
            ):
                self.server_data[guild.id].current_playing_url = ""

            player.skip()
            return Response(
                _D(
                    "Your skip for `%(track)s` was acknowledged.\n"
                    "The vote to skip has been passed.%(next_up)s",
                    ssd_,
                )
                % {
                    "track": _D(current_entry.title, ssd_),
                    "next_up": (
                        _D(" Next song coming up!", ssd_)
                        if player.playlist.peek()
                        else ""
                    ),
                },
            )

        # TODO: When a song gets skipped, delete the old x needed to skip messages
        if not permissions.skip_looped and player.repeatsong:
            raise exceptions.PermissionsError(
                "You do not have permission to skip a looped song.",
            )

        if player.repeatsong:
            player.repeatsong = False
        return Response(
            _D(
                "Your skip for `%(track)s` was acknowledged.\n"
                "Need **%(votes)s** more vote(s) to skip this song.",
                ssd_,
            )
            % {
                "track": _D(current_entry.title, ssd_),
                "votes": skips_remaining,
            },
        )

    @command_helper(
        usage=["{cmd} [VOLUME]"],
        desc=_Dd(
            "Set the output volume level of MusicBot from 1 to 100.\n"
            "Volume parameter allows a leading + or - for relative adjustments.\n"
            "The volume setting is retained until MusicBot is restarted.\n"
        ),
    )
    async def cmd_volume(
        self,
        ssd_: Optional[GuildSpecificData],
        player: MusicPlayer,
        new_volume: str = "",
    ) -> CommandResponse:
        """
        Command to set volume level of MusicBot output for the session.
        """

        if not new_volume:
            return Response(
                _D("Current volume: `%(volume)s%%`", ssd_)
                % {"volume": int(player.volume * 100)},
            )

        relative = False
        if new_volume[0] in "+-":
            relative = True

        try:
            int_volume = int(new_volume)

        except ValueError as e:
            raise exceptions.CommandError(
                "`%(new_volume)s` is not a valid number",
                fmt_args={"new_volume": new_volume},
            ) from e

        vol_change = 0
        if relative:
            vol_change = int_volume
            int_volume += int(player.volume * 100)

        old_volume = int(player.volume * 100)

        if 0 < int_volume <= 100:
            player.volume = int_volume / 100.0

            return Response(
                _D("Updated volume from **%(old)d** to **%(new)d**", ssd_)
                % {"old": old_volume, "new": int_volume},
            )

        if relative:
            raise exceptions.CommandError(
                "Unreasonable volume change provided: %(old_volume)s%(adjustment)s is %(new_volume)s.\n"
                "Volume can only be set from 1 to 100.",
                fmt_args={
                    "old_volume": old_volume,
                    "new_volume": old_volume + vol_change,
                    "adjustment": f"{vol_change:+}",
                },
            )

        raise exceptions.CommandError(
            "Unreasonable volume provided: %(volume)s. Provide a value between 1 and 100.",
            fmt_args={"volume": new_volume},
        )

    @command_helper(
        usage=["{cmd} [RATE]"],
        desc=_Dd(
            "Change the playback speed of the currently playing track only.\n"
            "The rate must be between 0.5 and 100.0 due to ffmpeg limits.\n"
            "Streaming playback does not support speed adjustments.\n"
        ),
    )
    async def cmd_speed(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        player: MusicPlayer,
        new_speed: str = "",
    ) -> CommandResponse:
        """
        Check for playing entry and apply a speed to ffmpeg for playback.
        """
        if not player.current_entry:
            raise exceptions.CommandError(
                "No track is playing, cannot set speed.\n"
                "Use the config command to set a default playback speed.",
            )

        if not isinstance(
            player.current_entry, (URLPlaylistEntry, LocalFilePlaylistEntry)
        ):
            raise exceptions.CommandError(
                "Speed cannot be applied to streamed media.",
            )

        if not new_speed:
            raise exceptions.CommandError(
                "You must provide a speed to set.",
            )

        try:
            speed = float(new_speed)
            if speed < 0.5 or speed > 100.0:
                raise ValueError("Value out of range.")
        except (ValueError, TypeError) as e:
            raise exceptions.CommandError(
                "The speed you provided is invalid. Use a number between 0.5 and 100.",
            ) from e

        # Set current playback progress and speed then restart playback.
        entry = player.current_entry
        entry.set_start_time(player.progress)
        entry.set_playback_speed(speed)
        player.playlist.insert_entry_at_index(0, entry)

        # handle history playlist updates.
        if (
            self.config.enable_queue_history_global
            or self.config.enable_queue_history_guilds
        ):
            self.server_data[guild.id].current_playing_url = ""

        player.skip()

        return Response(
            _D("Setting playback speed to `%(speed).3f` for current track.", ssd_)
            % {"speed": speed},
        )

    @owner_only
    @command_helper(
        # fmt: off
        usage=[
            "{cmd} add <ALIAS> <CMD> [ARGS]\n"
            + _Dd("    Add an new alias with optional arguments.\n"),

            "{cmd} remove <ALIAS>\n"
            + _Dd("    Remove an alias with the given name.\n"),

            "{cmd} <save | load>\n"
            + _Dd("    Reload or save aliases from/to the config file.\n"),
        ],
        # fmt: on
        desc=_Dd(
            "Allows management of aliases from discord. To see aliases use the help command."
        ),
        remap_subs={"+": "add", "-": "remove"},
    )
    async def cmd_setalias(
        self,
        ssd_: Optional[GuildSpecificData],
        opt: str,
        leftover_args: List[str],
        alias: str = "",
        cmd: str = "",
    ) -> CommandResponse:
        """
        Enable management of aliases from within discord.
        """
        opt = opt.lower()
        cmd = cmd.strip()
        args = " ".join(leftover_args)
        alias = alias.strip()
        if opt not in ["add", "remove", "save", "load"]:
            raise exceptions.CommandError(
                "Invalid option for command: `%(option)s`",
                fmt_args={"option": opt},
            )

        if opt == "load":
            self.aliases.load()
            return Response(_D("Aliases reloaded from config file.", ssd_))

        if opt == "save":
            try:
                self.aliases.save()
                return Response(_D("Aliases saved to config file.", ssd_))
            except (RuntimeError, OSError) as e:
                raise exceptions.CommandError(
                    "Failed to save aliases due to error:\n`%(raw_error)s`",
                    fmt_args={"raw_error": e},
                ) from e

        if opt == "add":
            if not alias or not cmd:
                raise exceptions.CommandError(
                    "You must supply an alias and a command to alias",
                )
            self.aliases.make_alias(alias, cmd, args)
            cmdstr = " ".join([cmd, args]).strip()
            return Response(
                _D(
                    "New alias added. `%(alias)s` is now an alias of `%(command)s`",
                    ssd_,
                )
                % {"alias": alias, "command": cmdstr}
            )

        if opt == "remove":
            if not alias:
                raise exceptions.CommandError(
                    "You must supply an alias name to remove.",
                )

            if not self.aliases.exists(alias):
                raise exceptions.CommandError(
                    "The alias `%(alias)s` does not exist.",
                    fmt_args={"alias": alias},
                )

            self.aliases.remove_alias(alias)
            return Response(
                _D("Alias `%(alias)s` was removed.", ssd_) % {"alias": alias}
            )

        return None

    @owner_only
    @command_helper(
        # fmt: off
        usage=[
            "{cmd} missing\n"
            + _Dd("    Shows help text about any missing config options.\n"),

            "{cmd} diff\n"
            + _Dd("    Lists the names of options which have been changed since loading config file.\n"),

            "{cmd} list\n"
            + _Dd("    List the available config options and their sections.\n"),

            "{cmd} reload\n"
            + _Dd("    Reload the options.ini file from disk.\n"),

            "{cmd} help <SECTION> <OPTION>\n"
            + _Dd("    Shows help text for a specific option.\n"),

            "{cmd} show <SECTION> <OPTION>\n"
            + _Dd("    Display the current value of the option.\n"),

            "{cmd} save <SECTION> <OPTION>\n"
            + _Dd("    Saves the current value to the options file.\n"),

            "{cmd} set <SECTION> <OPTION> <VALUE>\n"
            + _Dd("    Validates the option and sets the config for the session, but not to file.\n"),

            "{cmd} reset <SECTION> <OPTION>\n"
            + _Dd("    Reset the option to its default value.\n"),
        ],
        # fmt: on
        desc=_Dd("Manage options.ini configuration from within Discord."),
    )
    async def cmd_config(
        self,
        ssd_: Optional[GuildSpecificData],
        user_mentions: UserMentions,
        channel_mentions: List[discord.abc.GuildChannel],
        option: str,
        leftover_args: List[str],
    ) -> CommandResponse:
        """
        Command to enable complex management of options.ini config file.
        """
        if user_mentions and channel_mentions:
            raise exceptions.CommandError(
                "Config cannot use channel and user mentions at the same time.",
            )

        option = option.lower()
        valid_options = [
            "missing",
            "diff",
            "list",
            "save",
            "help",
            "show",
            "set",
            "reload",
            "reset",
        ]
        if option not in valid_options:
            raise exceptions.CommandError(
                "Invalid option for command: `%(option)s`",
                fmt_args={"option": option},
            )

        # Show missing options with help text.
        if option == "missing":
            missing = ""
            for opt in self.config.register.ini_missing_options:
                missing += _D(
                    "**Missing Option:** `%(config)s`\n"
                    "```\n"
                    "%(comment)s\n"
                    "Default is set to:  %(default)s"
                    "```\n",
                    ssd_,
                ) % {
                    "config": opt,
                    "comment": opt.comment,
                    "default": opt.default,
                }
            if not missing:
                missing = _D(
                    "*All config options are present and accounted for!*",
                    ssd_,
                )

            return Response(
                missing,
                delete_after=self.config.delete_delay_long,
            )

        # Show options names that have changed since loading.
        if option == "diff":
            changed = ""
            for opt in self.config.register.get_updated_options():
                changed += f"`{str(opt)}`\n"

            if not changed:
                changed = _D("No config options appear to be changed.", ssd_)
            else:
                changed = _D("**Changed Options:**\n%(changed)s", ssd_) % {
                    "changed": changed
                }

            return Response(
                changed,
                delete_after=self.config.delete_delay_long,
            )

        # List all available options.
        if option == "list":
            non_edit_opts = ""
            editable_opts = ""
            for opt in self.config.register.option_list:
                if opt.editable:
                    editable_opts += f"`{opt}`\n"
                else:
                    non_edit_opts += f"`{opt}`\n"

            opt_list = _D(
                "## Available Options:\n"
                "**Editable Options:**\n%(editable)s\n"
                "**Manual Edit Only:**\n%(manual)s",
                ssd_,
            ) % {
                "editable": editable_opts,
                "manual": non_edit_opts,
            }
            return Response(
                opt_list,
                delete_after=self.config.delete_delay_long,
            )

        # Try to reload options.ini file from disk.
        if option == "reload":
            try:
                new_conf = Config(self._config_file)
                await new_conf.async_validate(self)

                self.config = new_conf

                return Response(
                    _D("Config options reloaded from file successfully!", ssd_)
                )
            except Exception as e:
                raise exceptions.CommandError(
                    "Unable to reload Config due to the following error:\n%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

        # sub commands beyond here need 2 leftover_args
        if option in ["help", "show", "save", "set", "reset"]:
            largs = len(leftover_args)
            if (
                self.config.register.resolver_available
                and largs != 0
                and ((option == "set" and largs < 3) or largs < 2)
            ):
                # assume that section is omitted.
                possible_sections = self.config.register.get_sections_from_option(
                    leftover_args[0]
                )
                if len(possible_sections) == 0:
                    raise exceptions.CommandError(
                        "Could not resolve section name from option name. Please provide a valid section and option name.",
                    )
                if len(possible_sections) > 1:
                    raise exceptions.CommandError(
                        "The option given is ambiguous, please provide a section name.",
                    )
                # adjust the command arguments to include the resolved section.
                leftover_args = [list(possible_sections)[0]] + leftover_args
            elif largs < 2 or (option == "set" and largs < 3):
                raise exceptions.CommandError(
                    "You must provide a section name and option name for this command.",
                )

        # Get the command args from leftovers and check them.
        section_arg = leftover_args.pop(0)
        option_arg = leftover_args.pop(0)
        if user_mentions:
            leftover_args += [str(m.id) for m in user_mentions]
        if channel_mentions:
            leftover_args += [str(ch.id) for ch in channel_mentions]
        value_arg = " ".join(leftover_args)
        p_opt = self.config.register.get_config_option(section_arg, option_arg)

        if section_arg not in self.config.register.sections:
            sects = ", ".join(self.config.register.sections)
            raise exceptions.CommandError(
                "The section `%(section)s` is not available.\n"
                "The available sections are:  %(sections)s",
                fmt_args={"section": section_arg, "sections": sects},
            )

        if p_opt is None:
            option_arg = f"[{section_arg}] > {option_arg}"
            raise exceptions.CommandError(
                "The option `%(option)s` is not available.",
                fmt_args={"option": option_arg},
            )
        opt = p_opt

        # Display some commentary about the option and its default.
        if option == "help":
            default = _D(
                "This option can only be set by editing the config file.", ssd_
            )
            if opt.editable:
                default = _D(
                    "By default this option is set to: %(default)s",
                    ssd_,
                ) % {"default": opt.default}
            return Response(
                _D(
                    "**Option:** `%(config)s`\n%(comment)s\n\n%(default)s",
                    ssd_,
                )
                % {"config": opt, "comment": opt.comment, "default": default},
                delete_after=self.config.delete_delay_long,
            )

        # Save the current config value to the INI file.
        if option == "save":
            if not opt.editable:
                raise exceptions.CommandError(
                    "Option `%(option)s` is not editable. Cannot save to disk.",
                    fmt_args={"option": opt},
                )

            async with self.aiolocks["config_edit"]:
                saved = self.config.save_option(opt)

            if not saved:
                raise exceptions.CommandError(
                    "Failed to save the option:  `%(option)s`",
                    fmt_args={"option": opt},
                )
            return Response(
                _D(
                    "Successfully saved the option:  `%(config)s`",
                    ssd_,
                )
                % {"config": opt}
            )

        # Display the current config and INI file values.
        if option == "show":
            if not opt.editable:
                raise exceptions.CommandError(
                    "Option `%(option)s` is not editable, value cannot be displayed.",
                    fmt_args={"option": opt},
                )
            # TODO: perhaps make use of currently unused display value for empty configs.
            cur_val, ini_val, disp_val = self.config.register.get_values(opt)
            return Response(
                _D(
                    "**Option:** `%(config)s`\n"
                    "Current Value:  `%(loaded)s`\n"
                    "INI File Value:  `%(ini)s`",
                    ssd_,
                )
                % {
                    "config": opt,
                    "loaded": cur_val if cur_val == "" else disp_val,
                    "ini": ini_val if ini_val == "" else disp_val,
                }
            )

        # update a config variable, but don't save it.
        if option == "set":
            if not opt.editable:
                raise exceptions.CommandError(
                    "Option `%(option)s` is not editable. Cannot update setting.",
                    fmt_args={"option": opt},
                )

            if not value_arg:
                raise exceptions.CommandError(
                    "You must provide a section, option, and value for this sub command.",
                )

            log.debug(
                "Doing set with on %(config)s == %(value)s",
                {"config": opt, "value": value_arg},
            )
            async with self.aiolocks["config_update"]:
                updated = self.config.update_option(opt, value_arg)
            if not updated:
                raise exceptions.CommandError(
                    "Option `%(option)s` was not updated!",
                    fmt_args={"option": opt},
                )
            return Response(
                _D(
                    "Option `%(config)s` was updated for this session.\n"
                    "To save the change use `config save %(section)s %(option)s`",
                    ssd_,
                )
                % {"config": opt, "section": opt.section, "option": opt.option}
            )

        # reset an option to default value as defined in ConfigDefaults
        if option == "reset":
            if not opt.editable:
                raise exceptions.CommandError(
                    "Option `%(option)s` is not editable. Cannot reset to default.",
                    fmt_args={"option": opt},
                )

            # Use the default value from the option object
            default_value = self.config.register.to_ini(opt, use_default=True)

            # Prepare a user-friendly message for the reset operation
            # TODO look into option registry display code for use here
            reset_value_display = default_value if default_value else "an empty set"

            log.debug(
                "Resetting %(config)s to default %(value)s",
                {"config": opt, "value": default_value},
            )
            async with self.aiolocks["config_update"]:
                updated = self.config.update_option(opt, default_value)
            if not updated:
                raise exceptions.CommandError(
                    "Option `%(option)s` was not reset to default!",
                    fmt_args={"option": opt},
                )
            return Response(
                _D(
                    "Option `%(config)s` was reset to its default value `%(default)s`.\n"
                    "To save the change use `config save %(section)s %(option)s`",
                    ssd_,
                )
                % {
                    "config": opt,
                    "option": opt.option,
                    "section": opt.section,
                    "default": reset_value_display,
                }
            )

        return None

    @owner_only
    @command_helper(desc=_Dd("Deprecated command, use the config command instead."))
    async def cmd_option(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        option: str,
        value: str,
    ) -> CommandResponse:
        """
        Command previously used to change boolean options in config.
        Replaced by the config command.
        """
        raise exceptions.CommandError(
            "The option command is deprecated, use the config command instead.",
        )

    @owner_only
    @command_helper(
        usage=["{cmd} <info | clear | update>"],
        desc=_Dd(
            "Display information about cache storage or clear cache according to configured limits.\n"
            "Using update option will scan the cache for external changes before displaying details."
        ),
    )
    async def cmd_cache(
        self, ssd_: Optional[GuildSpecificData], opt: str = "info"
    ) -> CommandResponse:
        """
        Command to enable cache management from discord.
        """
        opt = opt.lower()
        if opt not in ["info", "update", "clear"]:
            raise exceptions.CommandError(
                "Invalid option specified, use: info, update, or clear"
            )

        # actually query the filesystem.
        if opt == "update":
            self.filecache.scan_audio_cache()
            # force output of info after we have updated it.
            opt = "info"

        # report cache info as it is.
        if opt == "info":
            save_videos = [_D("Disabled", ssd_), _D("Enabled", ssd_)][
                self.config.save_videos
            ]
            time_limit = _D("%(time)s days", ssd_) % {
                "time": self.config.storage_limit_days
            }
            size_limit = format_size_from_bytes(self.config.storage_limit_bytes)

            if not self.config.storage_limit_bytes:
                size_limit = _D("Unlimited", ssd_)

            if not self.config.storage_limit_days:
                time_limit = _D("Unlimited", ssd_)

            cached_bytes, cached_files = self.filecache.get_cache_size()
            return Response(
                _D(
                    "**Video Cache:** *%(state)s*\n"
                    "**Storage Limit:** *%(size)s*\n"
                    "**Time Limit:** *%(time)s*\n"
                    "\n"
                    "**Cached Now:  %(used)s in %(files)s file(s).",
                    ssd_,
                )
                % {
                    "state": save_videos,
                    "size": size_limit,
                    "time": time_limit,
                    "used": format_size_from_bytes(cached_bytes),
                    "files": cached_files,
                },
                delete_after=self.config.delete_delay_long,
            )

        # clear cache according to settings.
        if opt == "clear":
            if self.filecache.cache_dir_exists():
                if self.filecache.delete_old_audiocache():
                    return Response(
                        _D(
                            "Cache has been cleared.",
                            ssd_,
                        ),
                    )

                raise exceptions.CommandError(
                    "**Failed** to delete cache, check logs for more info...",
                )
            return Response(
                _D("No cache found to clear.", ssd_),
            )
        # TODO: maybe add a "purge" option that fully empties cache regardless of settings.
        return None

    @command_helper(
        usage=["{cmd} [PAGE]"],
        desc=_Dd(
            "Display information about the current player queue.\n"
            "Optional page number shows later entries in the queue.\n"
        ),
    )
    async def cmd_queue(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        channel: MessageableChannel,
        player: MusicPlayer,
        page: str = "0",
        update_msg: Optional[discord.Message] = None,
    ) -> CommandResponse:
        """
        Interactive display for player queue, which expires after inactivity.
        """

        # handle the page argument.
        page_number = 0
        if page:
            try:
                page_number = abs(int(page))
            except (ValueError, TypeError) as e:
                raise exceptions.CommandError(
                    "Queue page argument must be a whole number.",
                ) from e

        # check for no entries at all.
        total_entry_count = len(player.playlist.entries)
        if not total_entry_count:
            raise exceptions.CommandError(
                "There are no songs queued! Queue something with a play command.",
            )

        # now check if page number is out of bounds.
        pages_total = math.ceil(total_entry_count / self.config.queue_length)
        if page_number > pages_total:
            raise exceptions.CommandError(
                "Requested page number is out of bounds.\n"
                "There are **%(total)s** pages.",
                fmt_args={"total": pages_total},
            )

        # Get current entry info if any.
        current_progress = ""
        if player.is_playing and player.current_entry:
            song_progress = format_song_duration(player.progress)
            song_total = (
                format_song_duration(player.current_entry.duration_td)
                if player.current_entry.duration is not None
                else _D("(unknown duration)", ssd_)
            )
            added_by = _D("[autoplaylist]", ssd_)
            cur_entry_channel = player.current_entry.channel
            cur_entry_author = player.current_entry.author
            if cur_entry_channel and cur_entry_author:
                added_by = cur_entry_author.name

            current_progress = _D(
                "Currently playing: `%(title)s`\n"
                "Added by: `%(user)s`\n"
                "Progress: `[%(progress)s/%(total)s]`\n",
                ssd_,
            ) % {
                "title": _D(player.current_entry.title, ssd_),
                "user": added_by,
                "progress": song_progress,
                "total": song_total,
            }

        # calculate start and stop slice indices
        start_index = self.config.queue_length * page_number
        end_index = start_index + self.config.queue_length
        starting_at = start_index + 1  # add 1 to index for display.

        # add the tracks to the embed fields
        tracks_list = ""
        queue_segment = list(player.playlist.entries)[start_index:end_index]
        for idx, item in enumerate(queue_segment, starting_at):
            if item == player.current_entry:
                # TODO: remove this debug later
                log.debug("Skipped the current playlist entry.")
                continue

            added_by = _D("[autoplaylist]", ssd_)
            if item.channel and item.author:
                added_by = item.author.name

            tracks_list += _D(
                "**Entry #%(index)s:**"
                "Title: `%(title)s`\n"
                "Added by: `%(user)s\n\n",
                ssd_,
            ) % {"index": idx, "title": _D(item.title, ssd_), "user": added_by}

        embed = Response(
            _D(
                "%(progress)s"
                "There are `%(total)s` entries in the queue.\n"
                "Here are the next %(per_page)s songs, starting at song #%(start)s\n"
                "\n%(tracks)s",
                ssd_,
            )
            % {
                "progress": current_progress,
                "total": total_entry_count,
                "per_page": self.config.queue_length,
                "start": starting_at,
                "tracks": tracks_list,
            },
            title=_D("Songs in queue", ssd_),
            delete_after=self.config.delete_delay_long,
        )

        # handle sending or editing the queue message.
        if update_msg:
            q_msg = await self.safe_edit_message(update_msg, embed, send_if_fail=True)
        else:
            if pages_total <= 1:
                q_msg = await self.safe_send_message(channel, embed)
            else:
                q_msg = await self.safe_send_message(channel, embed)

        if pages_total <= 1:
            log.debug("Not enough entries to paginate the queue.")
            return None

        if not q_msg:
            log.warning("Could not post queue message, no message to add reactions to.")
            raise exceptions.CommandError(
                "Try that again. MusicBot couldn't make or get a reference to the queue message.\n"
                "If the issue persists, file a bug report."
            )

        # set up the page numbers to be used by reactions.
        # this essentially make the pages wrap around.
        prev_index = page_number - 1
        next_index = page_number + 1
        if prev_index < 0:
            prev_index = pages_total
        if next_index > pages_total:
            next_index = 0

        for r in [EMOJI_PREV_ICON, EMOJI_NEXT_ICON, EMOJI_CROSS_MARK_BUTTON]:
            await q_msg.add_reaction(r)

        def _check_react(reaction: discord.Reaction, user: discord.Member) -> bool:
            # Do not check for the requesting author, any reaction is valid.
            if not self.user:
                return False
            return q_msg.id == reaction.message.id and user.id != self.user.id

        try:
            reaction, _user = await self.wait_for(
                "reaction_add",
                timeout=self.config.delete_delay_long,
                check=_check_react,
            )
            if reaction.emoji == EMOJI_NEXT_ICON:
                await q_msg.clear_reactions()
                await self.cmd_queue(
                    ssd_, guild, channel, player, str(next_index), q_msg
                )

            if reaction.emoji == EMOJI_PREV_ICON:
                await q_msg.clear_reactions()
                await self.cmd_queue(
                    ssd_, guild, channel, player, str(prev_index), q_msg
                )

            if reaction.emoji == EMOJI_CROSS_MARK_BUTTON:
                await self.safe_delete_message(q_msg)

        except asyncio.TimeoutError:
            await self.safe_delete_message(q_msg)

        return None

    @command_helper(
        usage=["{cmd} [RANGE]"],
        desc=_Dd(
            "Search for and remove bot messages and commands from the calling text channel.\n"
            "Optionally supply a number of messages to search through, 50 by default 500 max.\n"
            "This command may be slow if larger ranges are given.\n"
        ),
    )
    async def cmd_clean(
        self,
        ssd_: Optional[GuildSpecificData],
        message: discord.Message,
        channel: MessageableChannel,
        guild: discord.Guild,
        author: discord.Member,
        search_range_str: str = "50",
    ) -> CommandResponse:
        """
        Uses channel.purge() to delete valid bot messages or commands from the calling channel.
        """

        try:
            float(search_range_str)  # lazy check
            search_range = min(int(search_range_str), 500)
        except ValueError:
            return Response(
                _D(
                    "Invalid parameter. Please provide a number of messages to search.",
                    ssd_,
                )
            )

        # TODO:  add alias names to the command names list here.
        # cmd_names = await self.gen_cmd_list(message)

        def is_possible_command_invoke(entry: discord.Message) -> bool:
            prefix_list = self.server_data[guild.id].command_prefix_list
            content = entry.content
            for prefix in prefix_list:
                if content.startswith(prefix):
                    content = content.replace(prefix, "", 1).strip()
                    if content:
                        # TODO: this should check for command names and alias names.
                        return True
            return False

        delete_invokes = True
        delete_all = (
            channel.permissions_for(author).manage_messages
            or self.config.owner_id == author.id
        )

        def check(message: discord.Message) -> bool:
            if is_possible_command_invoke(message) and delete_invokes:
                return delete_all or message.author == author
            return message.author == self.user

        if isinstance(
            channel,
            (discord.DMChannel, discord.GroupChannel, discord.PartialMessageable),
        ):
            # TODO: maybe fix this to work?
            raise exceptions.CommandError("Cannot use purge on private DM channel.")

        if channel.permissions_for(guild.me).manage_messages:
            deleted = await channel.purge(
                check=check, limit=search_range, before=message
            )
            return Response(
                _D("Cleaned up %(number)s message(s).", ssd_)
                % {"number": len(deleted)},
            )
        return ErrorResponse(
            _D("Bot does not have permission to manage messages.", ssd_)
        )

    @command_helper(
        usage=["{cmd} <URL>"],
        desc=_Dd("Dump the individual URLs of a playlist to a file."),
    )
    async def cmd_pldump(
        self,
        ssd_: Optional[GuildSpecificData],
        author: discord.Member,
        song_subject: str,
    ) -> CommandResponse:
        """
        Extracts all URLs from a playlist and create a file attachment with the resulting links.
        This method does not validate the resulting links are actually playable.
        """

        song_url = self.downloader.get_url_or_none(song_subject)
        if not song_url:
            raise exceptions.CommandError(
                "The given URL was not a valid URL.",
            )

        try:
            info = await self.downloader.extract_info(
                song_url, download=False, process=True
            )
        # TODO: i18n stuff with translatable exceptions.
        except Exception as e:
            raise exceptions.CommandError(
                "Could not extract info from input url\n%(raw_error)s\n",
                fmt_args={"raw_error": e},
            )

        if not info.get("entries", None):
            raise exceptions.CommandError("This does not seem to be a playlist.")

        filename = "playlist.txt"
        if info.title:
            safe_title = slugify(info.title)
            filename = f"playlist_{safe_title}.txt"

        with BytesIO() as fcontent:
            total = info.playlist_count or info.entry_count
            fcontent.write(f"# Title:  {info.title}\n".encode("utf8"))
            fcontent.write(f"# Total:  {total}\n".encode("utf8"))
            fcontent.write(f"# Extractor:  {info.extractor}\n\n".encode("utf8"))

            for item in info.get_entries_objects():
                # TODO: maybe add track-name as a comment?
                url = item.get_playable_url()
                line = f"{url}\n"
                fcontent.write(line.encode("utf8"))

            fcontent.seek(0)
            msg_str = _D("Here is the playlist dump for:  %(url)s", ssd_) % {
                "url": song_url
            }
            datafile = discord.File(fcontent, filename=filename)

            return Response(msg_str, send_to=author, files=[datafile], force_text=True)

    @command_helper(
        usage=["{cmd} [@USER]"],
        desc=_Dd(
            "Display your Discord User ID, or the ID of a mentioned user.\n"
            "This command is deprecated in favor of Developer Mode in Discord clients.\n"
        ),
    )
    async def cmd_id(
        self,
        ssd_: Optional[GuildSpecificData],
        author: discord.Member,
        user_mentions: UserMentions,
    ) -> CommandResponse:
        """
        Respond with the Discord User ID / snowflake.
        """
        if not user_mentions:
            return Response(
                _D("Your user ID is `%(id)s`", ssd_) % {"id": author.id},
            )

        usr = user_mentions[0]
        return Response(
            _D("The user ID for `%(username)s` is `%(id)s`", ssd_)
            % {"username": usr.name, "id": usr.id},
        )

    @command_helper(
        usage=["{cmd} [all | users | roles | channels]"],
        desc=_Dd(
            "List the Discord IDs for the selected category.\n"
            "Returns all ID data by default, but one or more categories may be selected.\n"
            "This command is deprecated in favor of using Developer mode in Discord clients.\n"
        ),
    )
    async def cmd_listids(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        author: discord.Member,
        leftover_args: List[str],
        cat: str = "all",
    ) -> CommandResponse:
        """
        Fetch discord IDs from the guild.
        """

        cats = ["channels", "roles", "users"]

        if cat not in cats and cat != "all":
            cats_str = " ".join([f"`{c}`" for c in cats])
            return Response(
                _D("Valid categories: %(cats)s", ssd_) % {"cats": cats_str},
            )

        if cat == "all":
            requested_cats = cats
        else:
            requested_cats = [cat] + [
                c.strip(",") for c in leftover_args if c.strip(",") in cats
            ]

        data = [f"Your ID: {author.id}"]

        for cur_cat in requested_cats:
            rawudata = None

            if cur_cat == "users":
                data.append("\nUser IDs:")
                rawudata = [
                    f"{m.name} #{m.discriminator}: {m.id}" for m in guild.members
                ]

            elif cur_cat == "roles":
                data.append("\nRole IDs:")
                rawudata = [f"{r.name}: {r.id}" for r in guild.roles]

            elif cur_cat == "channels":
                data.append("\nText Channel IDs:")
                tchans = [
                    c for c in guild.channels if isinstance(c, discord.TextChannel)
                ]
                rawudata = [f"{c.name}: {c.id}" for c in tchans]

                rawudata.append("\nVoice Channel IDs:")
                vchans = [
                    c for c in guild.channels if isinstance(c, discord.VoiceChannel)
                ]
                rawudata.extend(f"{c.name}: {c.id}" for c in vchans)

            if rawudata:
                data.extend(rawudata)

        with BytesIO() as sdata:
            slug = slugify(guild.name)
            fname = f"{slug}-ids-{cat}.txt"
            sdata.writelines(d.encode("utf8") + b"\n" for d in data)
            sdata.seek(0)
            datafile = discord.File(sdata, filename=fname)
            msg_str = _D("Here are the IDs you requested:", ssd_)

            return Response(msg_str, send_to=author, files=[datafile])

    @command_helper(
        usage=["{cmd} [@USER]"],
        desc=_Dd(
            "Get a list of your permissions, or the permissions of the mentioned user."
        ),
    )
    async def cmd_perms(
        self,
        ssd_: Optional[GuildSpecificData],
        author: discord.Member,
        user_mentions: UserMentions,
        guild: discord.Guild,
        permissions: PermissionGroup,
        target: str = "",
    ) -> CommandResponse:
        """
        Generate a permission report fit for human consumption, attempt to DM the data.
        """

        user: Optional[MessageAuthor] = None
        if user_mentions:
            user = user_mentions[0]

        if not user_mentions and not target:
            user = author

        if not user_mentions and target:
            getuser = guild.get_member_named(target)
            if getuser is None:
                try:
                    user = await self.fetch_user(int(target))
                except (discord.NotFound, ValueError) as e:
                    raise exceptions.CommandError(
                        "Invalid user ID or server nickname, please double-check the ID and try again.",
                    ) from e
            else:
                user = getuser

        if not user:
            raise exceptions.CommandError(
                "Could not determine the discord User.  Try again.",
            )

        permissions = self.permissions.for_user(user)

        if user == author:
            perms = _D(
                "Your command permissions in %(server)s are:\n"
                "```\n%(permissions)s\n```",
                ssd_,
            ) % {
                "server": guild.name,
                "permissions": permissions.format(for_user=True),
            }
        else:
            perms = _D(
                "The command permissions for %(username)s in %(server)s are:\n"
                "```\n%(permissions)s\n```",
                ssd_,
            ) % {
                "username": user.name,
                "server": guild.name,
                "permissions": permissions.format(),
            }

        return Response(perms, send_to=author)

    @owner_only
    @command_helper(
        # fmt: off
        usage=[
            "{cmd} list\n"
            + _Dd("    Show loaded groups and list permission options.\n"),

            "{cmd} reload\n"
            + _Dd("    Reloads permissions from the permissions.ini file.\n"),

            "{cmd} add <GROUP>\n"
            + _Dd("    Add new group with defaults.\n"),

            "{cmd} remove <GROUP>\n"
            + _Dd("    Remove existing group.\n"),

            "{cmd} help <PERMISSION>\n"
            + _Dd("    Show help text for the permission option.\n"),

            "{cmd} show <GROUP> <PERMISSION>\n"
            + _Dd("    Show permission value for given group and permission.\n"),

            "{cmd} save <GROUP>\n"
            + _Dd("    Save permissions group to file.\n"),

            "{cmd} set <GROUP> <PERMISSION> [VALUE]\n"
            + _Dd("    Set permission value for the group.\n"),
        ],
        # fmt: on
        desc=_Dd("Manage permissions.ini configuration from within discord."),
    )
    async def cmd_setperms(
        self,
        ssd_: Optional[GuildSpecificData],
        user_mentions: UserMentions,
        leftover_args: List[str],
        option: str = "list",
    ) -> CommandResponse:
        """
        Allows management of permissions.ini settings for the bot.
        """
        # TODO: add a method to clear / reset to default.
        if user_mentions:
            raise exceptions.CommandError(
                "Permissions cannot use channel and user mentions at the same time.",
            )

        option = option.lower()
        valid_options = [
            "list",
            "add",
            "remove",
            "save",
            "help",
            "show",
            "set",
            "reload",
        ]
        if option not in valid_options:
            raise exceptions.CommandError(
                "Invalid option for command: `%(option)s`",
                fmt_args={"option": option},
            )

        # Reload the permissions file from disk.
        if option == "reload":
            try:
                new_permissions = Permissions(self._perms_file)
                # Set the owner ID in case it wasn't auto...
                new_permissions.set_owner_id(self.config.owner_id)
                await new_permissions.async_validate(self)

                self.permissions = new_permissions

                return Response(
                    _D("Permissions reloaded from file successfully!", ssd_)
                )
            except Exception as e:
                raise exceptions.CommandError(
                    "Unable to reload Permissions due to an error:\n%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

        # List permission groups and available permission options.
        if option == "list":
            gl = []
            for section in self.permissions.register.sections:
                gl.append(f"`{section}`\n")

            editable_opts = ""
            for opt in self.permissions.register.option_list:
                if opt.section != DEFAULT_PERMS_GROUP_NAME:
                    continue

                # if opt.editable:
                editable_opts += f"`{opt.option}`\n"

            groups = "".join(gl)
            opt_list = _D(
                "## Available Groups:\n%(groups)s\n"
                "## Available Options:\n"
                "%(options)s\n",
                ssd_,
            ) % {
                "groups": groups,
                "options": editable_opts,
            }
            return Response(
                opt_list,
                delete_after=self.config.delete_delay_long,
            )

        # sub commands beyond here need 2 leftover_args
        if option in ["help", "show", "save", "add", "remove"]:
            if len(leftover_args) < 1:
                raise exceptions.CommandError(
                    "You must provide a group or option name for this command.",
                )
        if option == "set" and len(leftover_args) < 3:
            raise exceptions.CommandError(
                "You must provide a group, option, and value to set for this command.",
            )

        # Get the command args from leftovers and check them.
        group_arg = ""
        option_arg = ""
        if option == "help":
            group_arg = DEFAULT_PERMS_GROUP_NAME
            option_arg = leftover_args.pop(0)
        else:
            group_arg = leftover_args.pop(0)
        if option in ["set", "show"]:
            if not leftover_args:
                raise exceptions.CommandError(
                    "The %(option)s sub-command requires a group and permission name.",
                    fmt_args={"option": option},
                )
            option_arg = leftover_args.pop(0)

        if user_mentions:
            leftover_args += [str(m.id) for m in user_mentions]
        value_arg = " ".join(leftover_args)

        if group_arg not in self.permissions.register.sections and option != "add":
            sects = ", ".join(self.permissions.register.sections)
            raise exceptions.CommandError(
                "The group `%(group)s` is not available.\n"
                "The available groups are:  %(sections)s",
                fmt_args={"group": group_arg, "sections": sects},
            )

        # Make sure the option is set if the sub-command needs it.
        if option in ["help", "set", "show"]:
            p_opt = self.permissions.register.get_config_option(group_arg, option_arg)
            if p_opt is None:
                option_arg = f"[{group_arg}] > {option_arg}"
                raise exceptions.CommandError(
                    "The permission `%(option)s` is not available.",
                    fmt_args={"option": option_arg},
                )
            opt = p_opt

        # Display some commentary about the option and its default.
        if option == "help":
            default = _D(
                "This permission can only be set by editing the permissions file.",
                ssd_,
            )
            # TODO:  perhaps use empty display values here.
            if opt.editable:
                dval = self.permissions.register.to_ini(opt, use_default=True)
                if dval == "":
                    dval = " "
                default = _D(
                    "By default this permission is set to: `%(value)s`",
                    ssd_,
                ) % {"value": dval}
            return Response(
                _D(
                    "**Permission:** `%(option)s`\n%(comment)s\n\n%(default)s",
                    ssd_,
                )
                % {
                    "option": opt.option,
                    "comment": opt.comment,
                    "default": default,
                },
                delete_after=self.config.delete_delay_long,
            )

        if option == "add":
            if group_arg in self.permissions.register.sections:
                raise exceptions.CommandError(
                    "Cannot add group `%(group)s` it already exists.",
                    fmt_args={"group": group_arg},
                )
            async with self.aiolocks["permission_edit"]:
                self.permissions.add_group(group_arg)

            return Response(
                _D(
                    "Successfully added new group:  `%(group)s`\n"
                    "You can now customize the permissions with:  `setperms set %(group)s`\n"
                    "Make sure to save the new group with:  `setperms save %(group)s`",
                    ssd_,
                )
                % {"group": group_arg}
            )

        if option == "remove":
            if group_arg in [DEFAULT_OWNER_GROUP_NAME, DEFAULT_PERMS_GROUP_NAME]:
                raise exceptions.CommandError("Cannot remove built-in group.")

            async with self.aiolocks["permission_edit"]:
                self.permissions.remove_group(group_arg)

            return Response(
                _D(
                    "Successfully removed group:  `%(group)s`\n"
                    "Make sure to save this change with:  `setperms save %(group)s`",
                    ssd_,
                )
                % {"group": group_arg}
            )

        # Save the current config value to the INI file.
        if option == "save":
            if group_arg == DEFAULT_OWNER_GROUP_NAME:
                raise exceptions.CommandError(
                    "The owner group is not editable.",
                )

            async with self.aiolocks["permission_edit"]:
                saved = self.permissions.save_group(group_arg)

            if not saved:
                raise exceptions.CommandError(
                    "Failed to save the group:  `%(group)s`",
                    fmt_args={"group": group_arg},
                )
            return Response(
                _D("Successfully saved the group:  `%(group)s`", ssd_)
                % {"group": group_arg}
            )

        # Display the current permissions group and INI file values.
        if option == "show":
            cur_val, ini_val, empty_display_val = self.permissions.register.get_values(
                opt
            )
            return Response(
                _D(
                    "**Permission:** `%(permission)s`\n"
                    "Current Value:  `%(loaded)s`\n"
                    "INI File Value:  `%(ini)s`",
                    ssd_,
                )
                % {
                    "permission": opt,
                    "loaded": cur_val if cur_val == "" else empty_display_val,
                    "ini": ini_val if ini_val == "" else empty_display_val,
                },
            )

        # update a permission, but don't save it.
        if option == "set":
            if group_arg == DEFAULT_OWNER_GROUP_NAME:
                raise exceptions.CommandError(
                    "The owner group is not editable.",
                )

            if not value_arg:
                raise exceptions.CommandError(
                    "You must provide a section, option, and value for this sub command.",
                )

            log.debug(
                "Doing set on %(option)s with value: %(value)s",
                {"option": opt, "value": value_arg},
            )
            async with self.aiolocks["permission_update"]:
                updated = self.permissions.update_option(opt, value_arg)
            if not updated:
                raise exceptions.CommandError(
                    "Permission `%(option)s` was not updated!",
                    fmt_args={"option": opt},
                )
            return Response(
                _D(
                    "Permission `%(permission)s` was updated for this session.\n"
                    "To save the change use `setperms save %(section)s %(option)s`",
                    ssd_,
                )
                % {
                    "permission": opt,
                    "section": opt.section,
                    "option": opt.option,
                }
            )

        return None

    @owner_only
    @command_helper(
        usage=["{cmd} <NAME>"],
        desc=_Dd(
            "Change the bot's username on discord.\n"
            "Note: The API may limit name changes to twice per hour."
        ),
    )
    async def cmd_setname(
        self, ssd_: Optional[GuildSpecificData], leftover_args: List[str], name: str
    ) -> CommandResponse:
        """
        Update the bot's username on discord.
        """

        name = " ".join([name, *leftover_args])

        try:
            if self.user:
                await self.user.edit(username=name)

        except discord.HTTPException as e:
            raise exceptions.CommandError(
                "Failed to change username. Did you change names too many times?\n"
                "Remember name changes are limited to twice per hour.\n"
            ) from e

        except Exception as e:
            raise exceptions.CommandError(
                "Failed to change username due to error:  \n%(raw_error)s",
                fmt_args={"raw_error": e},
            ) from e

        return Response(
            _D("Set the bot's username to `%(name)s`", ssd_) % {"name": name}
        )

    @command_helper(usage=["{cmd} <NICK>"], desc=_Dd("Change the MusicBot's nickname."))
    async def cmd_setnick(
        self,
        ssd_: Optional[GuildSpecificData],
        guild: discord.Guild,
        channel: MessageableChannel,
        leftover_args: List[str],
        nick: str,
    ) -> CommandResponse:
        """
        Update the bot nickname.
        """

        if not channel.permissions_for(guild.me).change_nickname:
            raise exceptions.CommandError("Unable to change nickname: no permission.")

        nick = " ".join([nick, *leftover_args])

        try:
            await guild.me.edit(nick=nick)
        except Exception as e:
            raise exceptions.CommandError(
                "Failed to set nickname due to error:  \n%(raw_error)s",
                fmt_args={"raw_error": e},
            ) from e

        return Response(
            _D("Set the bot's nickname to `%(nick)s`", ssd_) % {"nick": nick}
        )

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} <PREFIX>\n"
            + _Dd("    Set a per-server command prefix."),
            "{cmd} clear\n"
            + _Dd("    Clear the per-server command prefix."),
        ],
        # fmt: on
        desc=_Dd(
            "Override the default command prefix in the server.\n"
            "The option EnablePrefixPerGuild must be enabled first."
        ),
    )
    async def cmd_setprefix(
        self, ssd_: Optional[GuildSpecificData], prefix: str
    ) -> CommandResponse:
        """
        Override the command prefix for the calling guild.
        """
        if ssd_ and self.config.enable_options_per_guild:
            # TODO: maybe filter odd unicode or bad words...
            # Filter custom guild emoji, bot can only use in-guild emoji.
            emoji_match = re.match(r"^<a?:(.+):(\d+)>$", prefix)
            if emoji_match:
                _e_name, e_id = emoji_match.groups()
                try:
                    emoji = self.get_emoji(int(e_id))
                except ValueError:
                    emoji = None
                if not emoji:
                    raise exceptions.CommandError(
                        "Custom emoji must be from this server to use as a prefix.",
                    )

            if "clear" == prefix:
                ssd_.command_prefix = ""
                await ssd_.save_guild_options_file()
                return Response(_D("Server command prefix is cleared.", ssd_))

            ssd_.command_prefix = prefix
            await ssd_.save_guild_options_file()
            return Response(
                _D("Server command prefix is now:  %(prefix)s", ssd_)
                % {"prefix": prefix},
                delete_after=self.config.delete_delay_long,
            )

        raise exceptions.CommandError(
            "Prefix per server is not enabled!\n"
            "Use the config command to update the prefix instead.",
        )

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} show\n"
            + _Dd("    Show language codes available to use.\n"),

            "{cmd} set [LOCALE]\n"
            + _Dd("    Set the desired language for this server.\n"),

            "{cmd} reset\n"
            + _Dd("    Reset the server language to bot's default language.\n"),
        ],
        # fmt: on
        desc=_Dd("Manage the language used for messages in the calling server."),
    )
    async def cmd_language(
        self,
        ssd_: Optional[GuildSpecificData],
        subcmd: str = "show",
        lang_code: str = "",
    ) -> CommandResponse:
        """
        Allow management of per-server language settings.
        This does not depend on an option, outside of default language.
        """
        if not ssd_:
            raise exceptions.CommandError("This command can only be used in guilds.")

        subcmd = subcmd.lower()
        if subcmd not in ["show", "set", "reset"]:
            raise exceptions.CommandError(
                "Invalid sub-command given. Use the help command for more information."
            )

        langdir = pathlib.Path(DEFAULT_I18N_DIR)
        available_langs = set()
        for f in langdir.glob("*/LC_MESSAGES/*.mo"):
            available_langs.add(f.parent.parent.name)

        if subcmd == "show":
            return Response(
                _D(
                    "**Current Language:** `%(locale)s`\n"
                    "**Available Languages:**\n```\n%(languages)s```",
                    ssd_,
                )
                % {"locale": ssd_.lang_code, "languages": ", ".join(available_langs)}
            )

        if subcmd == "set":
            if lang_code not in available_langs:
                raise exceptions.CommandError(
                    "Cannot set language to `%(locale)s` it is not available.",
                    fmt_args={"locale": ssd_.lang_code},
                )
            ssd_.lang_code = lang_code
            return Response(
                _D("Language for this server now set to: `%(locale)s`", ssd_)
                % {"locale": lang_code},
            )

        if subcmd == "reset":
            ssd_.lang_code = ""
            return Response(
                _D(
                    "Language for this server has been reset to: `%(locale)s`",
                    ssd_,
                )
                % {"locale": DEFAULT_I18N_LANG},
            )

        return None

    @owner_only
    @command_helper(
        usage=["{cmd} [URL]"],
        desc=_Dd(
            "Change MusicBot's avatar.\n"
            "Attaching a file and omitting the url parameter also works.\n"
        ),
    )
    async def cmd_setavatar(
        self,
        ssd_: Optional[GuildSpecificData],
        message: discord.Message,
        av_url: str = "",
    ) -> CommandResponse:
        """
        Update the bot avatar with an image URL or attachment.
        """

        url = self.downloader.get_url_or_none(av_url)
        if message.attachments:
            thing = message.attachments[0].url
        elif url:
            thing = url
        else:
            raise exceptions.CommandError("You must provide a URL or attach a file.")

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            if self.user and self.session:
                async with self.session.get(thing, timeout=timeout) as res:
                    await self.user.edit(avatar=await res.read())

        except Exception as e:
            raise exceptions.CommandError(
                "Unable to change avatar due to error:  \n%(raw_error)s",
                fmt_args={"raw_error": e},
            ) from e

        return Response(_D("Changed the bot's avatar.", ssd_))

    @command_helper(
        desc=_Dd("Force MusicBot to disconnect from the discord server."),
    )
    async def cmd_disconnect(self, guild: discord.Guild) -> CommandResponse:
        """
        Forcibly disconnect the voice client from the calling server.
        """
        ssd = self.server_data[guild.id]
        voice_client = self.get_player_in(guild)
        if voice_client:
            await self.disconnect_voice_client(guild)
            return Response(
                _D("Disconnected from server `%(guild)s`", ssd) % {"guild": guild.name},
            )

        # check for a raw voice client instead.
        for vc in self.voice_clients:
            if not hasattr(vc.channel, "guild"):
                log.warning(
                    "MusicBot found a %s with no guild!  This could be a problem.",
                    type(vc),
                )
                continue

            if vc.channel.guild and vc.channel.guild == guild:
                await self.disconnect_voice_client(guild)
                return Response(
                    _D("Disconnected a playerless voice client? [BUG]", ssd)
                )

        raise exceptions.CommandError(
            "Not currently connected to server `%(guild)s`",
            fmt_args={"guild": guild.name},
        )

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} [soft]\n"
            + _Dd("    Attempt to reload without process restart. The default option.\n"),
            "{cmd} full\n"
            + _Dd("    Attempt to restart the entire MusicBot process, reloading everything.\n"),
            "{cmd} uppip\n"
            + _Dd("    Full restart, but attempt to update pip packages before restart.\n"),
            "{cmd} upgit\n"
            + _Dd("    Full restart, but update MusicBot source code with git first.\n"),
            "{cmd} upgrade\n"
            + _Dd("    Attempt to update all dependency and source code before fully restarting.\n"),
        ],
        # fmt: on
        desc=_Dd(
            "Attempts to restart the MusicBot in a number of different ways.\n"
            "With no option supplied, a `soft` restart is implied.\n"
            "It can be used to remotely update a MusicBot installation, but should be used with care.\n"
            "If you have a service manager, we recommend using it instead of this command for restarts.\n"
        ),
    )
    async def cmd_restart(
        self,
        _player: Optional[MusicPlayer],
        guild: discord.Guild,
        channel: MessageableChannel,
        opt: str = "soft",
    ) -> CommandResponse:
        """
        Usage:
            {command_prefix}restart [soft|full|upgrade|upgit|uppip]
        """
        # TODO:  move the update stuff to its own command, including update check.
        opt = opt.strip().lower()
        if opt not in ["soft", "full", "upgrade", "uppip", "upgit"]:
            raise exceptions.CommandError(
                "Invalid option given, use one of:  soft, full, upgrade, uppip, or upgit"
            )

        out_msg = ""
        if opt == "soft":
            out_msg = _D(
                "%(emoji)s Restarting current instance...",
                self.server_data[guild.id],
            ) % {"emoji": EMOJI_RESTART_SOFT}
        elif opt == "full":
            out_msg = _D(
                "%(emoji)s Restarting bot process...",
                self.server_data[guild.id],
            ) % {"emoji": EMOJI_RESTART_FULL}
        elif opt == "uppip":
            out_msg = _D(
                "%(emoji)s Will try to upgrade required pip packages and restart the bot...",
                self.server_data[guild.id],
            ) % {"emoji": EMOJI_UPDATE_PIP}
        elif opt == "upgit":
            out_msg = _D(
                "%(emoji)s Will try to update bot code with git and restart the bot...",
                self.server_data[guild.id],
            ) % {"emoji": EMOJI_UPDATE_GIT}
        elif opt == "upgrade":
            out_msg = _D(
                "%(emoji)s Will try to upgrade everything and restart the bot...",
                self.server_data[guild.id],
            ) % {"emoji": EMOJI_UPDATE_ALL}

        await self.safe_send_message(channel, Response(out_msg))

        if _player and _player.is_paused:
            _player.resume()

        await self.disconnect_all_voice_clients()
        if opt == "soft":
            raise exceptions.RestartSignal(code=exceptions.RestartCode.RESTART_SOFT)

        if opt == "full":
            raise exceptions.RestartSignal(code=exceptions.RestartCode.RESTART_FULL)

        if opt == "upgrade":
            raise exceptions.RestartSignal(
                code=exceptions.RestartCode.RESTART_UPGRADE_ALL
            )

        if opt == "uppip":
            raise exceptions.RestartSignal(
                code=exceptions.RestartCode.RESTART_UPGRADE_PIP
            )

        if opt == "upgit":
            raise exceptions.RestartSignal(
                code=exceptions.RestartCode.RESTART_UPGRADE_GIT
            )

        return None

    @command_helper(
        desc=_Dd("Disconnect from all voice channels and close the MusicBot process.")
    )
    async def cmd_shutdown(
        self, guild: discord.Guild, channel: MessageableChannel
    ) -> CommandResponse:
        """
        Disconnects from voice channels and raises the TerminateSignal
        which is hopefully respected by all the loopy async processes
        and then results in MusicBot cleanly shutting down.
        """
        await self.safe_send_message(
            channel,
            Response("\N{WAVING HAND SIGN}", force_text=True),
        )

        player = self.get_player_in(guild)
        if player and player.is_paused:
            player.resume()

        await self.disconnect_all_voice_clients()
        raise exceptions.TerminateSignal()

    @command_helper(
        # fmt: off
        usage=[
            "{cmd} <NAME | ID>\n"
            + _Dd("   Leave the discord server given by name or server ID."),
        ],
        # fmt: on
        desc=_Dd(
            "Force MusicBot to leave the given Discord server.\n"
            "Names are case-sensitive, so using an ID number is more reliable.\n"
        ),
    )
    async def cmd_leaveserver(
        self, ssd_: Optional[GuildSpecificData], val: str, leftover_args: List[str]
    ) -> CommandResponse:
        """
        Forces the bot to leave a server.
        """
        guild_id = 0
        guild_name = ""
        if leftover_args:
            guild_name = " ".join([val, *leftover_args])

        try:
            guild_id = int(val)
        except ValueError as e:
            if not guild_name:
                raise exceptions.CommandError("You must provide an ID or name.") from e

        if guild_id:
            leave_guild = self.get_guild(guild_id)

        if leave_guild is None:
            # Get guild by name
            leave_guild = discord.utils.get(self.guilds, name=guild_name)

        if leave_guild is None:
            raise exceptions.CommandError(
                "No guild was found with the ID or name `%(input)s`",
                fmt_args={"input": val},
            )

        await leave_guild.leave()

        guild_name = leave_guild.name
        guild_owner = (
            leave_guild.owner.name if leave_guild.owner else _D("Unknown Owner", ssd_)
        )
        guild_id = leave_guild.id
        # TODO: this response doesn't make sense if the command is issued
        # from within the server being left.
        return Response(
            _D(
                "Left the guild: `%(name)s` (Owner: `%(owner)s`, ID: `%(id)s`)",
                ssd_,
            )
            % {"name": guild_name, "owner": guild_owner, "id": guild_id}
        )

    @dev_only
    @command_helper(
        usage=["{cmd} [dry]"],
        desc=_Dd("Command used to automate testing of commands."),
    )
    async def cmd_testready(
        self, message: discord.Message, opt: str = ""
    ) -> CommandResponse:
        """Command used to signal command testing."""
        cmd_list = await self.gen_cmd_list(message, list_all_cmds=True)

        from .testrig import run_cmd_tests

        dry = False
        if opt.lower() == "dry":
            dry = True

        await run_cmd_tests(self, message, cmd_list, dry)

        return Response(
            f"Tested commands:\n```\n{', '.join(cmd_list)}```", force_text=True
        )

    @dev_only
    @command_helper(
        desc=_Dd(
            "This command issues a log at level CRITICAL, but does nothing else.\n"
            "Can be used to manually pinpoint events in the MusicBot log file.\n"
        ),
    )
    async def cmd_breakpoint(self, guild: discord.Guild) -> CommandResponse:
        """
        Do nothing but print a critical level error to the log.
        """
        uid = str(uuid.uuid4())
        ssd = self.server_data[guild.id]
        log.critical("Activating debug breakpoint ID: %(uuid)s", {"uuid": uid})
        return Response(_D("Logged breakpoint with ID:  %(uuid)s", ssd) % {"uuid": uid})

    @dev_only
    @command_helper(
        # fmt: off
        usage=[
            "{cmd}\n"
            + _Dd("    View most common types reported by objgraph.\n"),

            "{cmd} growth\n"
            + _Dd("    View limited objgraph.show_growth() output.\n"),

            "{cmd} leaks\n"
            + _Dd("    View most common types of leaking objects.\n"),

            "{cmd} leakstats\n"
            + _Dd("    View typestats of leaking objects.\n"),

            "{cmd} [objgraph.function(...)]\n"
            + _Dd("    Evaluate the given function and arguments on objgraph.\n"),
        ],
        # fmt: on
        desc=_Dd(
            "Interact with objgraph, if it is installed, to gain insight into memory usage.\n"
            "You can pass an arbitrary method with arguments (but no spaces!) that is a member of objgraph.\n"
            "Since this method evaluates arbitrary code, it is considered dangerous like the debug command.\n"
        )
    )
    async def cmd_objgraph(
        self,
        message: discord.Message,  # pylint: disable=unused-argument
        channel: MessageableChannel,
        func: str = "most_common_types()",
    ) -> CommandResponse:
        """
        Interact with objgraph to make it spill the beans.
        """
        if not objgraph:
            raise exceptions.CommandError(
                "Could not import `objgraph`, is it installed?"
            )

        await channel.typing()

        if func == "growth":
            f = StringIO()
            objgraph.show_growth(limit=10, file=f)
            f.seek(0)
            data = f.read()
            f.close()

        elif func == "leaks":
            f = StringIO()
            objgraph.show_most_common_types(
                objects=objgraph.get_leaking_objects(), file=f
            )
            f.seek(0)
            data = f.read()
            f.close()

        elif func == "leakstats":
            data = objgraph.typestats(objects=objgraph.get_leaking_objects())

        else:
            data = eval("objgraph." + func)  # pylint: disable=eval-used

        return Response(data, codeblock="py")

    @dev_only
    @command_helper(
        # fmt: off
        usage=[
            "{cmd} [PYCODE]\n",
        ],
        # fmt: on
        desc=_Dd(
            "This command will execute arbitrary python code in the command scope.\n"
            "First eval() is attempted, if exceptions are thrown exec() is tried next.\n"
            "If eval is successful, it's return value is displayed.\n"
            "If exec is successful, a value can be set to local variable `result` and that value will be returned.\n"
            "\n"
            "Multi-line code can be executed if wrapped in code-block.\n"
            "Otherwise only a single line may be executed.\n"
            "\n"
            "This command may be removed in a future version, and is used by developers to debug MusicBot behaviour.\n"
            "The danger of this command cannot be understated. Do not use it or give access to it if you do not understand the risks!\n"
        ),
    )
    async def cmd_debug(
        self,
        _player: Optional[MusicPlayer],
        message: discord.Message,  # pylint: disable=unused-argument
        channel: GuildMessageableChannels,  # pylint: disable=unused-argument
        guild: discord.Guild,  # pylint: disable=unused-argument
        author: discord.Member,  # pylint: disable=unused-argument
        permissions: PermissionGroup,  # pylint: disable=unused-argument
        *,
        data: str,
    ) -> CommandResponse:
        """
        Command for debugging MusicBot in real-time.
        It is dangerous and should maybe be removed in later versions...
        """
        codeblock = "```py\n{}\n```"
        result = None

        if data.startswith("```") and data.endswith("```"):
            code = "\n".join(data.lstrip("`").rstrip("`\n").split("\n")[1:])
        else:
            code = data.strip("` \n")

        try:
            run_type = "eval"
            result = eval(code)  # pylint: disable=eval-used
            log.debug("Debug code ran with eval().")
        except Exception:  # pylint: disable=broad-exception-caught
            try:
                run_type = "exec"
                # exec needs a fake locals so we can get `result` from it.
                lscope: Dict[str, Any] = {}
                # exec also needs locals() to be in globals() for access to work.
                gscope = globals().copy()
                gscope.update(locals().copy())
                exec(code, gscope, lscope)  # pylint: disable=exec-used
                log.debug("Debug code ran with exec().")
                result = lscope.get("result", result)
            except Exception as e:
                log.exception("Debug code failed to execute.")
                raise exceptions.CommandError(
                    "Failed to execute debug code:\n%(py_code)s\n"
                    "Exception: ```\n%(ex_name)s:\n%(ex_text)s```",
                    fmt_args={
                        "py_code": codeblock.format(code),
                        "ex_name": type(e).__name__,
                        "ex_text": e,
                    },
                ) from e

        if asyncio.iscoroutine(result):
            result = await result

        return Response(f"**{run_type}() Result:**\n{codeblock.format(result)}")

    @dev_only
    @command_helper(
        usage=["{cmd} < opts | perms | help >"],
        desc=_Dd(
            "Create 'markdown' for options, permissions, or commands from the code.\n"
            "The output is used to update GitHub Pages and is thus unsuitable for normal reference use."
        ),
    )
    async def cmd_makemarkdown(
        self,
        author: discord.Member,
        cfg: str = "opts",
    ) -> CommandResponse:
        """
        Command to generate markdown from various documentation in the code.
        The output is intended to update github pages and is thus unsuitable for normal use.
        """
        valid_opts = ["opts", "perms", "help"]
        if cfg not in valid_opts:
            opts = " ".join([f"`{o}`" for o in valid_opts])
            raise exceptions.CommandError(
                "Sub-command must be one of: %(options)s",
                fmt_args={"options": opts},
            )

        filename = "unknown.md"
        msg_str = ""
        if cfg == "opts":
            filename = "config_options.md"
            msg_str = "Config options described in Markdown:\n"
            config_md = self.config.register.export_markdown()

        if cfg == "perms":
            filename = "config_permissions.md"
            msg_str = "Permissions described in Markdown:\n"
            config_md = self.permissions.register.export_markdown()

        if cfg == "help":
            filename = "commands_help.md"
            msg_str = "All the commands and their usage attached."
            config_md = "### General Commands  \n\n"
            admin_commands = []
            dev_commands = []
            for att in dir(self):
                if att.startswith("cmd_"):
                    cmd = getattr(self, att, None)
                    doc = await self.gen_cmd_help(
                        att.replace("cmd_", ""), None, for_md=True
                    )
                    command_name = att.replace("cmd_", "").lower()
                    cmd_a = hasattr(cmd, "admin_only")
                    cmd_d = hasattr(cmd, "dev_cmd")
                    command_text = f"<details>\n  <summary>{command_name}</summary>\n{doc}\n</details>\n\n"
                    if cmd_a:
                        admin_commands.append(command_text)
                        continue
                    if cmd_d:
                        dev_commands.append(command_text)
                        continue
                    config_md += command_text
            config_md += f"### Owner Commands  \n\n{''.join(admin_commands)}"
            config_md += f"### Dev Commands  \n\n{''.join(dev_commands)}"

        with BytesIO() as fcontent:
            fcontent.write(config_md.encode("utf8"))
            fcontent.seek(0)
            datafile = discord.File(fcontent, filename=filename)

            return Response(msg_str, send_to=author, files=[datafile], force_text=True)

    @dev_only
    @command_helper(desc=_Dd("Makes default INI files."))
    async def cmd_makeini(
        self,
        ssd_: Optional[GuildSpecificData],
        cfg: str = "opts",
    ) -> CommandResponse:
        """Generates an example ini file, used for comparing example_options.ini to documentation in code."""
        valid_opts = ["opts", "perms"]
        if cfg not in valid_opts:
            opts = " ".join([f"`{o}`" for o in valid_opts])
            raise exceptions.CommandError(
                "Sub-command must be one of: %(options)s",
                fmt_args={"options": opts},
            )

        if cfg == "opts":
            self.config.register.write_default_ini(write_path(EXAMPLE_OPTIONS_FILE))

        if cfg == "perms":
            self.permissions.register.write_default_ini(write_path(EXAMPLE_PERMS_FILE))

        return Response(_D("Saved the requested INI file to disk. Go check it", ssd_))

    @owner_only
    @command_helper(
        desc=_Dd(
            "Display the current bot version and check for updates to MusicBot or dependencies.\n"
        ),
    )
    async def cmd_checkupdates(
        self, ssd_: Optional[GuildSpecificData], channel: MessageableChannel
    ) -> CommandResponse:
        """
        Usage:
            {command_prefix}checkupdates

        Display the current bot version and check for updates to MusicBot or dependencies.
        The option `GitUpdatesBranch` must be set to check for updates to MusicBot.
        """
        git_status = ""
        pip_status = ""
        updates = False

        await channel.typing()

        # attempt fetching git info.
        try:
            git_bin = shutil.which("git")
            if not git_bin:
                git_status = "Could not locate git executable."
                raise exceptions.CommandError("Could not locate git executable.")

            git_cmd_branch = [git_bin, "rev-parse", "--abbrev-ref", "HEAD"]
            git_cmd_check = [git_bin, "fetch", "--dry-run"]

            # extract current git branch name.
            cmd_branch = await asyncio.create_subprocess_exec(
                *git_cmd_branch,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            branch_stdout, _stderr = await cmd_branch.communicate()
            branch_name = branch_stdout.decode("utf8").strip()

            # check if fetch would update.
            cmd_check = await asyncio.create_subprocess_exec(
                *git_cmd_check,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            check_stdout, check_stderr = await cmd_check.communicate()
            check_stdout += check_stderr
            lines = check_stdout.decode("utf8").split("\n")

            # inspect dry run for our branch name to see if there are updates.
            commit_to = ""
            for line in lines:
                parts = line.split()
                if branch_name in parts:
                    commits = line.strip().split(" ", maxsplit=1)[0]
                    _commit_at, commit_to = commits.split("..")
                    break

            if not commit_to:
                git_status = _D("No updates in branch `%(branch)s` remote.", ssd_) % {
                    "branch": branch_name
                }
            else:
                git_status = _D(
                    "New commits are available in `%(branch)s` branch remote.",
                    ssd_,
                ) % {"branch": branch_name}
                updates = True
        except (OSError, ValueError, ConnectionError, RuntimeError):
            log.exception("Failed while checking for updates via git command.")
            git_status = _D("Error while checking, see logs for details.", ssd_)

        # attempt to fetch pip info.
        try:
            pip_cmd_check = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-U",
                "-r",
                "./requirements.txt",
                "--quiet",
                "--dry-run",
                "--report",
                "-",
            ]
            pip_cmd = await asyncio.create_subprocess_exec(
                *pip_cmd_check,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            pip_stdout, _stderr = await pip_cmd.communicate()
            pip_json = json.loads(pip_stdout)
            pip_packages = ""
            for pkg in pip_json.get("install", []):
                meta = pkg.get("metadata", {})
                if not meta:
                    log.debug("Package missing meta in pip report.")
                    continue
                name = meta.get("name", "")
                ver = meta.get("version", "")
                if name and ver:
                    pip_packages += _D(
                        "Update for `%(name)s` to version: `%(version)s`\n", ssd_
                    ) % {"name": name, "version": ver}
            if pip_packages:
                pip_status = pip_packages
                updates = True
            else:
                pip_status = _D("No updates for dependencies found.", ssd_)
        except (OSError, ValueError, ConnectionError):
            log.exception("Failed to get pip update status due to some error.")
            pip_status = _D("Error while checking, see logs for details.", ssd_)

        if updates:
            header = _D("There are updates for MusicBot available for download.", ssd_)
        else:
            header = _D("MusicBot is totally up-to-date!", ssd_)

        return Response(
            _D(
                "%(status)s\n\n"
                "**Source Code Updates:**\n%(git_status)s\n\n"
                "**Dependency Updates:**\n%(pip_status)s",
                ssd_,
            )
            % {
                "status": header,
                "git_status": git_status,
                "pip_status": pip_status,
            },
            delete_after=self.config.delete_delay_long,
        )

    @command_helper(
        desc=_Dd("Displays the MusicBot uptime, or time since last start / restart."),
    )
    async def cmd_uptime(self, ssd_: Optional[GuildSpecificData]) -> CommandResponse:
        """
        Usage:
            {command_prefix}uptime

        Displays the MusicBot uptime, since last start/restart.
        """
        uptime = time.time() - self._init_time
        delta = format_song_duration(uptime)
        name = DEFAULT_BOT_NAME
        if self.user:
            name = self.user.name
        return Response(
            _D("%(name)s has been online for `%(time)s`", ssd_)
            % {"name": name, "time": delta},
        )

    @owner_only
    @command_helper(
        desc=_Dd(
            "Display latency information for Discord API and all connected voice clients."
        ),
    )
    async def cmd_botlatency(
        self, ssd_: Optional[GuildSpecificData]
    ) -> CommandResponse:
        """
        Command botlatency Prints latency info for everything.
        """
        vclats = ""
        for vc in self.voice_clients:
            if not isinstance(vc, discord.VoiceClient) or not hasattr(
                vc.channel, "rtc_region"
            ):
                log.debug("Got a strange voice client entry.")
                continue

            vl = vc.latency * 1000
            vla = vc.average_latency * 1000
            # Display Auto for region instead of None
            region = vc.channel.rtc_region or "auto"
            vclats += _D(
                "- `%(delay).0f ms` (`%(avg).0f ms` Avg.) in region: `%(region)s`\n",
                ssd_,
            ) % {"delay": vl, "avg": vla, "region": region}

        if not vclats:
            vclats = _D("No voice clients connected.\n", ssd_)

        sl = self.latency * 1000
        return Response(
            _D(
                "**API Latency:** `%(delay).0f ms`\n"
                "**VoiceClient Latency:**\n%(voices)s",
                ssd_,
            )
            % {"delay": sl, "voices": vclats}
        )

    @command_helper(
        desc=_Dd("Display API latency and Voice latency if MusicBot is connected."),
    )
    async def cmd_latency(
        self, ssd_: Optional[GuildSpecificData], guild: discord.Guild
    ) -> CommandResponse:
        """
        Command latency for current guild / voice connections.
        """

        voice_lat = ""
        if guild.id in self.players:
            vc = self.players[guild.id].voice_client
            if vc:
                vl = vc.latency * 1000
                vla = vc.average_latency * 1000
                # TRANSLATORS: short for automatic, displayed when voice region is not selected.
                vcr = vc.channel.rtc_region or _D("auto", ssd_)
                voice_lat = _D(
                    "\n**Voice Latency:** `%(delay).0f ms` (`%(average).0f ms` Avg.) in region `%(region)s`",
                    ssd_,
                ) % {"delay": vl, "average": vla, "region": vcr}
        sl = self.latency * 1000
        return Response(
            _D("**API Latency:** `%(delay).0f ms`%(voice)s", ssd_)
            % {"delay": sl, "voice": voice_lat},
        )

    @command_helper(
        desc=_Dd("Display MusicBot version number in the chat."),
    )
    async def cmd_botversion(
        self, ssd_: Optional[GuildSpecificData]
    ) -> CommandResponse:
        """Command to check MusicBot version string in discord."""
        return Response(
            _D(
                "https://github.com/Just-Some-Bots/MusicBot\n"
                "Current version:  `%(version)s`",
                ssd_,
            )
            % {"version": BOTVERSION}
        )

    @owner_only
    @command_helper(
        # fmt: off
        usage=[
            "{cmd}\n"
            + _Dd("    Update the cookies.txt file using a cookies.txt attachment."),

            "{cmd} [off | on]\n"
            + _Dd("    Enable or disable cookies.txt file without deleting it."),
        ],
        # fmt: on
        desc=_Dd(
            "Allows management of the cookies feature in yt-dlp.\n"
            "When updating cookies, you must upload a file named cookies.txt\n"
            "If cookies are disabled, uploading will enable the feature.\n"
            "Uploads will delete existing cookies, including disabled cookies file.\n"
            "\n"
            "WARNING:\n"
            "  Copying cookies can risk exposing your personal information or accounts,\n"
            "  and may result in account bans or theft if you are not careful.\n"
            "  It is not recommended due to these risks, and you should not use this\n"
            "  feature if you do not understand how to avoid the risks."
        ),
    )
    async def cmd_setcookies(
        self, ssd_: Optional[GuildSpecificData], message: discord.Message, opt: str = ""
    ) -> CommandResponse:
        """
        setcookies command allows management of yt-dlp cookies feature.
        """
        opt = opt.lower()
        if opt == "on":
            if self.downloader.cookies_enabled:
                raise exceptions.CommandError("Cookies already enabled.")

            if (
                not self.config.disabled_cookies_path.is_file()
                and not self.config.cookies_path.is_file()
            ):
                raise exceptions.CommandError(
                    "Cookies must be uploaded to be enabled. (Missing cookies file.)"
                )

            # check for cookies file and use it.
            if self.config.cookies_path.is_file():
                self.downloader.enable_ytdl_cookies()
            else:
                # or rename the file as needed.
                try:
                    self.config.disabled_cookies_path.rename(self.config.cookies_path)
                    self.downloader.enable_ytdl_cookies()
                except OSError as e:
                    raise exceptions.CommandError(
                        "Could not enable cookies due to error:  %(raw_error)s",
                        fmt_args={"raw_error": e},
                    ) from e
            return Response(_D("Cookies have been enabled.", ssd_))

        if opt == "off":
            if self.downloader.cookies_enabled:
                self.downloader.disable_ytdl_cookies()

            if self.config.cookies_path.is_file():
                try:
                    self.config.cookies_path.rename(self.config.disabled_cookies_path)
                except OSError as e:
                    raise exceptions.CommandError(
                        "Could not rename cookies file due to error:  %(raw_error)s\n"
                        "Cookies temporarily disabled and will be re-enabled on next restart.",
                        fmt_args={"raw_error": e},
                    ) from e
            return Response(_D("Cookies have been disabled.", ssd_))

        # check for attached files and inspect them for use.
        if not message.attachments:
            raise exceptions.CommandError(
                "No attached uploads were found, try again while uploading a cookie file."
            )

        # check for a disabled cookies file and remove it.
        if self.config.disabled_cookies_path.is_file():
            try:
                self.config.disabled_cookies_path.unlink()
            except OSError as e:
                log.warning(
                    "Could not remove old, disabled cookies file:  %(raw_error)s",
                    {"raw_error": e},
                )

        # simply save the uploaded file in attachment 1 as cookies.txt.
        try:
            await message.attachments[0].save(self.config.cookies_path)
        except discord.HTTPException as e:
            raise exceptions.CommandError(
                "Error downloading the cookies file from discord:  %(raw_error)s",
                fmt_args={"raw_error": e},
            ) from e
        except OSError as e:
            raise exceptions.CommandError(
                "Could not save cookies to disk:  %(raw_error)s",
                fmt_args={"raw_error": e},
            ) from e

        # enable cookies if it is not already.
        if not self.downloader.cookies_enabled:
            self.downloader.enable_ytdl_cookies()

        return Response(_D("Cookies uploaded and enabled.", ssd_))

    async def on_message(self, message: discord.Message) -> None:
        """
        Event called by discord.py when any message is sent to/around the bot.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_message
        """
        await self.wait_until_ready()

        if not message.channel:
            log.debug("Got a message with no channel, somehow:  %s", message)
            return

        if message.channel.guild:
            command_prefix = self.server_data[message.channel.guild.id].command_prefix
        else:
            command_prefix = self.config.command_prefix
        message_content = message.content.strip()
        # if the prefix is an emoji, silently remove the space often auto-inserted after it.
        # this regex will get us close enough to knowing if an unicode emoji is in the prefix...
        emoji_regex = re.compile(r"^(<a?:.+:\d+>|:.+:|[^ -~]+)$")
        if emoji_regex.match(command_prefix):
            message_content = message_content.replace(
                f"{command_prefix} ", command_prefix, 1
            )

        # lastly check if we allow bot mentions for commands.
        self_mention = "<@MusicBot>"  # placeholder
        if self.user:
            self_mention = f"<@{self.user.id}>"
        if not message_content.startswith(command_prefix) and (
            self.config.commands_via_mention
            and not message_content.startswith(self_mention)
        ):
            return

        # ignore self
        if message.author == self.user:
            log.warning("Ignoring command from myself (%s)", message.content)
            return

        # ignore bots
        if (
            message.author.bot
            and message.author.id not in self.config.bot_exception_ids
        ):
            log.warning("Ignoring command from other bot (%s)", message.content)
            return

        # ignore any channel type we can't respond to. Also type checking.
        if (not isinstance(message.channel, discord.abc.GuildChannel)) and (
            not isinstance(message.channel, discord.abc.PrivateChannel)
        ):
            log.warning(
                "Ignoring command from channel of type:  %s", type(message.channel)
            )
            return

        # if via mentions, we treat the mention as a prefix for args extraction.
        if self.config.commands_via_mention and message_content.startswith(
            self_mention
        ):
            # replace the space often included after mentions.
            message_content = message_content.replace(
                f"{self_mention} ", self_mention, 1
            )
            command_prefix = self_mention

        # handle spaces inside of a command prefix.
        # this is only possible through manual edits to the config.
        if " " in command_prefix:
            invalid_prefix = command_prefix
            command_prefix = command_prefix.replace(" ", "_")
            message_content = message_content.replace(invalid_prefix, command_prefix, 1)

        # Extract the command name and args from the message content.
        command, *args = message_content.split(" ")
        command = command[len(command_prefix) :].lower().strip()

        # Check if the incomming command is a "natural" command.
        handler = getattr(self, "cmd_" + command, None)
        if not handler:
            # If no natural command was found, check for aliases when enabled.
            if self.config.usealias:
                # log.debug("Checking for alias with: %s", command)
                command, alias_arg_str = self.aliases.from_alias(command)
                handler = getattr(self, "cmd_" + command, None)
                if not handler:
                    return
                # log.debug("Alias found:  %s %s", command, alias_arg_str)
                # Complex aliases may have args of their own.
                # We assume the user args go after the alias args.
                if alias_arg_str:
                    args = alias_arg_str.split(" ") + args
            # Or ignore aliases, and this non-existent command.
            else:
                return

        # Legacy / Backwards compat, remap alternative sub-command args.
        args = getattr(handler, "remap_subcommands", list)(args)

        # check for private channel usage, only limited commands can be used in DM.
        if isinstance(message.channel, discord.abc.PrivateChannel):
            if not (
                message.author.id == self.config.owner_id
                and getattr(handler, "cmd_in_dm", False)
            ):
                await self.safe_send_message(
                    message.channel,
                    ErrorResponse(
                        _D("You cannot use this bot in private messages.", None)
                    ),
                )
                return

        # Make sure we only listen in guild channels we are bound to.
        # Unless unbound servers are allowed in addition to bound ones.
        if (
            self.config.bound_channels
            and message.guild
            and message.channel.id not in self.config.bound_channels
        ):
            if self.config.unbound_servers:
                if any(
                    c.id in self.config.bound_channels for c in message.guild.channels
                ):
                    return
            else:
                # log.everything("Unbound channel (%s) in server:  %s", message.channel, message.guild)
                return

        # check for user id or name in blacklist.
        if (
            self.config.user_blocklist.is_blocked(message.author)
            and message.author.id != self.config.owner_id
        ):
            # TODO:  maybe add a config option to enable telling users they are blocked.
            log.warning(
                "User in block list: %(id)s/%(name)s  tried command: %(command)s",
                {"id": message.author.id, "name": message.author, "comand": command},
            )
            return

        # all command validation checks passed, log a successful message
        log.info(
            "Message from %(id)s/%(name)s: %(message)s",
            {
                "id": message.author.id,
                "name": message.author,
                "message": message_content.replace("\n", "\n... "),
            },
        )

        # Get user's musicbot permissions for use in later checks and commands.
        user_permissions = self.permissions.for_user(message.author)

        # Extract the function signature of the cmd_* command to assign proper values later.
        argspec = inspect.signature(handler)
        params = argspec.parameters.copy()
        response: Optional[MusicBotResponse] = None
        ssd = None
        if message.channel.guild:
            ssd = self.server_data[message.channel.guild.id]

        # Check permissions, assign arguments, and process the command call.
        try:
            # check non-voice permission.
            if (
                user_permissions.ignore_non_voice
                and command in user_permissions.ignore_non_voice
            ):
                await self._check_ignore_non_voice(message)

            # Test for command permissions.
            if (
                message.author.id != self.config.owner_id
                and not user_permissions.can_use_command(command, args[0])
            ):
                raise exceptions.PermissionsError(
                    "This command is not allowed for your permissions group:  %(group)s",
                    fmt_args={"group": user_permissions.name},
                )

            # populate the requested command signature args.
            handler_kwargs: Dict[str, Any] = {}
            if params.pop("message", None):
                handler_kwargs["message"] = message

            if params.pop("channel", None):
                handler_kwargs["channel"] = message.channel

            if params.pop("author", None):
                handler_kwargs["author"] = message.author

            if params.pop("guild", None):
                handler_kwargs["guild"] = message.guild

            # this is the player-required arg, it prompts to be summoned if not already in voice.
            # or otherwise denies use if non-guild voice is used.
            if params.pop("player", None):
                # however, it needs a voice channel to connect to.
                if (
                    isinstance(message.author, discord.Member)
                    and message.guild
                    and message.author.voice
                    and message.author.voice.channel
                ):
                    handler_kwargs["player"] = await self.get_player(
                        message.author.voice.channel, create=user_permissions.summonplay
                    )
                else:
                    # TODO: enable ignore-non-voice commands to work here
                    # by looking for the first available VC if author has none.
                    raise exceptions.CommandError(
                        "This command requires you to be in a Voice channel."
                    )

            # this is the optional-player arg.
            if params.pop("_player", None):
                if message.guild:
                    handler_kwargs["_player"] = self.get_player_in(message.guild)
                else:
                    handler_kwargs["_player"] = None

            if params.pop("permissions", None):
                handler_kwargs["permissions"] = user_permissions

            # this arg only works in guilds.
            if params.pop("user_mentions", None):

                def member_or_user(
                    uid: int,
                ) -> Optional[Union[discord.Member, discord.User]]:
                    if message.guild:
                        m = message.guild.get_member(uid)
                        if m:
                            return m
                    return self.get_user(uid)

                handler_kwargs["user_mentions"] = []
                for um_id in message.raw_mentions:
                    m = member_or_user(um_id)
                    if m is not None:
                        handler_kwargs["user_mentions"].append(m)

            # this arg only works in guilds.
            if params.pop("channel_mentions", None):
                if message.guild:
                    handler_kwargs["channel_mentions"] = list(
                        map(message.guild.get_channel, message.raw_channel_mentions)
                    )
                else:
                    handler_kwargs["channel_mentions"] = []

            if params.pop("voice_channel", None):
                if message.guild:
                    handler_kwargs["voice_channel"] = (
                        message.guild.me.voice.channel
                        if message.guild.me.voice
                        else None
                    )
                else:
                    handler_kwargs["voice_channel"] = None

            if params.pop("ssd_", None):
                handler_kwargs["ssd_"] = ssd

            if params.pop("leftover_args", None):
                handler_kwargs["leftover_args"] = args

            for key, param in list(params.items()):
                # parse (*args) as a list of args
                if param.kind == param.VAR_POSITIONAL:
                    handler_kwargs[key] = args
                    params.pop(key)
                    continue

                # parse (*, args) as args rejoined as a string
                # multiple of these arguments will have the same value
                if param.kind == param.KEYWORD_ONLY and param.default == param.empty:
                    handler_kwargs[key] = " ".join(args)
                    params.pop(key)
                    continue

                # Ignore keyword args with default values when the command had no arguments
                if not args and param.default is not param.empty:
                    params.pop(key)
                    continue

                # Assign given values to positional arguments
                if args:
                    arg_value = args.pop(0)
                    handler_kwargs[key] = arg_value
                    params.pop(key)

            # Invalid usage, return docstring
            if params:
                log.debug(
                    "Invalid command usage, missing values for params: %(params)r",
                    {"params": params},
                )
                response = await self.cmd_help(
                    ssd, message, message.channel.guild, command
                )
                if response:
                    response.reply_to = message
                    await self.safe_send_message(message.channel, response)
                return

            response = await handler(**handler_kwargs)
            if response and isinstance(response, MusicBotResponse):
                # Set a default response title if none is set.
                if not response.title:
                    response.title = _D("**Command:** %(name)s", ssd) % {
                        "name": command
                    }

                # Determine if the response goes to a calling channel or a DM.
                send_kwargs: Dict[str, Any] = {}
                send_to = message.channel
                if response.send_to:
                    send_to = response.send_to
                    response.sent_from = message.channel

                # always reply to the caller, no reason not to.
                response.reply_to = message

                # remove footer if configured.
                if self.config.remove_embed_footer:
                    response.remove_footer()

                await self.safe_send_message(send_to, response, **send_kwargs)

        except (
            exceptions.CommandError,
            exceptions.HelpfulError,
            exceptions.ExtractionError,
            exceptions.MusicbotException,
        ) as e:
            log.error(
                "Error in %(command)s: %(err_name)s: %(err_text)s",
                {
                    "command": command,
                    "err_name": e.__class__.__name__,
                    "err_text": _L(e.message) % e.fmt_args,
                },
                exc_info=True,
            )
            er = ErrorResponse(
                _D(e.message, ssd) % e.fmt_args,
                codeblock="text",
                title="Error",
                reply_to=message,
                no_footer=self.config.remove_embed_footer,
            )
            await self.safe_send_message(message.channel, er)

        # raise custom signals for shutdown and restart.
        except exceptions.Signal:
            raise

        # Catch everything else to keep bugs from bringing down the bot...
        except Exception:  # pylint: disable=broad-exception-caught
            log.error(
                "Exception while handling command: %(command)s",
                {"command": command},
                exc_info=self.config.debug_mode,
            )
            if self.config.debug_mode:
                er = ErrorResponse(
                    traceback.format_exc(),
                    codeblock="text",
                    title=_D("Exception Error", ssd),
                    reply_to=message,
                    no_footer=self.config.remove_embed_footer,
                )
                await self.safe_send_message(message.channel, er)

        finally:
            if self.config.delete_invoking:
                self.create_task(
                    self._wait_delete_msg(message, self.config.delete_delay_short)
                )

    async def gen_cmd_help(
        self, cmd_name: str, guild: Optional[discord.Guild], for_md: bool = False
    ) -> str:
        """
        Generates help for the given command from documentation in code.

        :param: cmd_name:  The command to get help for.
        :param: guild:  Guild where the call comes from.
        :param: for_md:  If true, output as "markdown" for Github Pages.
        """
        cmd = getattr(self, f"cmd_{cmd_name}", None)
        if not cmd:
            log.debug("Cannot generate help for missing command:  %s", cmd_name)
            return ""

        if not hasattr(cmd, "help_usage") or not hasattr(cmd, "help_desc"):
            log.critical("Missing help data for command:  %s", cmd_name)

        cmd_usage = getattr(cmd, "help_usage", [])
        cmd_desc = getattr(cmd, "help_desc", "")
        emoji_prefix = False
        ssd = None
        if guild:
            ssd = self.server_data[guild.id]
            prefix_l = ssd.command_prefix
        else:
            prefix_l = self.config.command_prefix
        # Its OK to skip unicode emoji here, they render correctly inside of code boxes.
        emoji_regex = re.compile(r"^(<a?:.+:\d+>|:.+:)$")
        prefix_note = ""
        if emoji_regex.match(prefix_l):
            emoji_prefix = True
            prefix_note = _D(
                "**Example with prefix:**\n%(prefix)s`%(command)s ...`\n",
                ssd,
            ) % {"prefix": prefix_l, "command": cmd_name}

        desc = _D(cmd_desc, ssd) or _D("No description given.\n", ssd)
        if desc[-1] != "\n":
            desc += "\n"
        usage = _D("No usage given.", ssd)
        if cmd_usage and isinstance(cmd_usage, list):
            cases = []
            for case in cmd_usage:
                if "\n" in case:
                    bits = case.split("\n", maxsplit=1)
                    example = bits[0]
                    text = ""
                    if len(bits) > 1 and bits[1]:
                        text = "\n"
                        text += _D(bits[1], ssd)
                    cases.append(f"{example}{text}")
                else:
                    cases.append(case)
            usage = "\n".join(cases)
            if emoji_prefix:
                usage = usage.replace("{prefix}", "")
            else:
                usage = usage.replace("{prefix}", prefix_l)

        if for_md:
            usage = usage.replace(prefix_l, "")
            # usage = usage.replace("\n", "<br>\n")
            desc = desc.replace("\n", "<br>\n")
            return (
                "<strong>Example usage:</strong><br>  \n"
                "{%% highlight text %%}\n"
                "%(usage)s\n"
                "{%% endhighlight %%}\n"
                "<strong>Description:</strong><br>  \n"
                "%(desc)s"
            ) % {"usage": usage, "desc": desc}

        return _D(
            "**Example usage:**\n"
            "```%(usage)s```\n"
            "%(prefix_note)s"
            "**Description:**\n"
            "%(desc)s",
            ssd,
        ) % {"usage": usage, "prefix_note": prefix_note, "desc": desc}

    async def gen_cmd_list(
        self, message: discord.Message, list_all_cmds: bool = False
    ) -> List[str]:
        """
        Return a list of valid command names, without prefix, for the given message author.
        Commands marked with @dev_cmd are never included.

        Param `list_all_cmds` set True will list commands regardless of permission restrictions.
        """
        commands = []
        for att in dir(self):
            # This will always return at least cmd_help, since they needed perms to run this command
            if att.startswith("cmd_") and not hasattr(getattr(self, att), "dev_cmd"):
                user_permissions = self.permissions.for_user(message.author)
                command_name = att.replace("cmd_", "").lower()
                whitelist = user_permissions.command_whitelist
                blacklist = user_permissions.command_blacklist
                if list_all_cmds:
                    commands.append(command_name)

                elif blacklist and command_name in blacklist:
                    pass

                elif whitelist and command_name not in whitelist:
                    pass

                else:
                    commands.append(command_name)
        return commands

    async def on_inactivity_timeout_expired(
        self, voice_channel: VoiceableChannel
    ) -> None:
        """
        A generic event called by MusicBot when configured channel or player
        activity timers reach their end.
        """
        guild = voice_channel.guild

        if isinstance(voice_channel, (discord.VoiceChannel, discord.StageChannel)):
            ssd = self.server_data[guild.id]
            last_np_msg = ssd.last_np_msg
            if last_np_msg is not None and last_np_msg.channel:
                channel = last_np_msg.channel
                r = Response(
                    _D("Leaving voice channel %(channel)s due to inactivity.", ssd)
                    % {"channel": voice_channel.name},
                )
                await self.safe_send_message(channel, r)

            log.info(
                "Leaving voice channel %s in %s due to inactivity.",
                voice_channel.name,
                voice_channel.guild,
            )
            await self.disconnect_voice_client(guild)

    async def on_connect(self) -> None:
        """Event called by discord.py when the Client has connected to the API."""
        if self.init_ok:
            log.info("MusicBot has become connected.")

    async def on_disconnect(self) -> None:
        """Event called by discord.py any time bot is disconnected, or fails to connect."""
        log.info("MusicBot has become disconnected.")

    async def on_socket_event_type(self, event_type: str) -> None:
        """Event called by discord.py on any socket event."""
        log.everything(  # type: ignore[attr-defined]
            "Got a Socket Event:  %s", event_type
        )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """
        Event called by discord.py when a VoiceClient changes state in any way.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_voice_state_update
        """
        if not self.init_ok:
            if self.config.debug_mode:
                log.warning(
                    "VoiceState updated before on_ready finished"
                )  # TODO: remove after coverage testing
            return  # Ignore stuff before ready

        guild = member.guild
        follow_user = self.server_data[guild.id].follow_user

        if self.config.leave_inactive_channel and not follow_user:
            event = self.server_data[guild.id].get_event("inactive_vc_timer")

            if before.channel and self.user in before.channel.members:
                if str(before.channel.id) in str(self.config.autojoin_channels):
                    log.info(
                        "Ignoring %s in %s as it is a bound voice channel.",
                        before.channel.name,
                        before.channel.guild,
                    )

                elif is_empty_voice_channel(
                    before.channel, include_bots=self.config.bot_exception_ids
                ):
                    log.info(
                        "%s has been detected as empty. Handling timeouts.",
                        before.channel.name,
                    )
                    self.create_task(
                        self.handle_vc_inactivity(guild), name="MB_HandleInactiveVC"
                    )
            elif after.channel and member != self.user:
                if self.user in after.channel.members:
                    if event.is_active():
                        # Added to not spam the console with the message for every person that joins
                        log.info(
                            "A user joined %s, cancelling timer.",
                            after.channel.name,
                        )
                    event.set()

            if (
                member == self.user and before.channel and after.channel
            ):  # bot got moved from channel to channel
                # if not any(not user.bot for user in after.channel.members):
                if is_empty_voice_channel(
                    after.channel, include_bots=self.config.bot_exception_ids
                ):
                    log.info(
                        "The bot got moved and the voice channel %s is empty. Handling timeouts.",
                        after.channel.name,
                    )
                    self.create_task(
                        self.handle_vc_inactivity(guild), name="MB_HandleInactiveVC"
                    )
                else:
                    if event.is_active():
                        log.info(
                            "The bot got moved and the voice channel %s is not empty.",
                            after.channel.name,
                        )
                        event.set()

        # Voice state updates for bot itself.
        if member == self.user:
            # check if bot was disconnected from a voice channel
            if not after.channel and before.channel and not self.network_outage:
                if await self._handle_api_disconnect(before):
                    return

            # if the bot was moved to a stage channel, request speaker.
            # similarly, make the bot request speaker when suppressed.
            if (
                after.channel != before.channel
                and after.suppress
                and isinstance(after.channel, discord.StageChannel)
            ) or (
                after.channel == before.channel
                and after.suppress
                and before.suppress
                and after.requested_to_speak_at is None
                and isinstance(after.channel, discord.StageChannel)
            ):
                try:
                    log.info(
                        "MusicBot is requesting to speak in channel: %s",
                        after.channel.name,
                    )
                    # this has the same effect as edit(suppress=False)
                    await after.channel.guild.me.request_to_speak()
                except discord.Forbidden:
                    log.exception("MusicBot does not have permission to speak.")
                except (discord.HTTPException, discord.ClientException):
                    log.exception("MusicBot could not request to speak.")

        if before.channel:
            player = self.get_player_in(before.channel.guild)
            if player and not follow_user:
                await self._handle_guild_auto_pause(player)
        if after.channel:
            player = self.get_player_in(after.channel.guild)
            if player and not follow_user:
                await self._handle_guild_auto_pause(player)

        if follow_user and member.id == follow_user.id:
            # follow-user has left the server voice channels.
            if after.channel is None:
                log.debug("No longer following user %s", member)
                self.server_data[member.guild.id].follow_user = None
                if player and not self.server_data[member.guild.id].auto_join_channel:
                    await self._handle_guild_auto_pause(player)
                if player and self.server_data[member.guild.id].auto_join_channel:
                    if (
                        player.voice_client.channel
                        != self.server_data[member.guild.id].auto_join_channel
                    ):
                        # move_to does not support setting deafen flags nor keep
                        # the flags set from initial connection.
                        # await player.voice_client.move_to(
                        #     self.server_data[member.guild.id].auto_join_channel
                        # )
                        await member.guild.change_voice_state(
                            channel=self.server_data[member.guild.id].auto_join_channel,
                            self_deaf=self.config.self_deafen,
                        )

            # follow-user has moved to a new channel.
            elif before.channel != after.channel and player:
                log.debug(
                    "Following user `%(user)s` to channel:  %(channel)s",
                    {"user": member, "channel": after.channel},
                )
                if player.is_playing:
                    player.pause()
                # using move_to does not respect the self-deafen flags from connect
                # nor does it allow us to set them...
                # await player.voice_client.move_to(after.channel)
                await member.guild.change_voice_state(
                    channel=after.channel,
                    self_deaf=self.config.self_deafen,
                )
                if player.is_paused:
                    player.resume()

    async def _handle_api_disconnect(self, before: discord.VoiceState) -> bool:
        """
        Method called from on_voice_state_update when MusicBot is disconnected from voice.
        """
        if not before.channel:
            log.debug("VoiceState disconnect before.channel is None.")
            return False

        o_guild = self.get_guild(before.channel.guild.id)
        o_vc: Optional[discord.VoiceClient] = None
        close_code: Optional[int] = None
        state: Optional[Any] = None
        if o_guild is not None and isinstance(
            o_guild.voice_client, discord.VoiceClient
        ):
            o_vc = o_guild.voice_client
            # borrow this for logging sake.
            close_code = (
                o_vc._connection.ws._close_code  # pylint: disable=protected-access
            )
            state = o_vc._connection.state  # pylint: disable=protected-access

        # These conditions are met when API terminates a voice client.
        # This could be a user initiated disconnect, but we have no way to tell.
        # Normally VoiceClients should auto-reconnect. However attempting to wait
        # by using VoiceClient.wait_until_connected() never seems to resolve.
        if (
            o_guild is not None
            and ((o_vc and not o_vc.is_connected()) or o_vc is None)
            and o_guild.id in self.players
        ):
            log.info(
                "Disconnected from voice by Discord API in: %(guild)s/%(channel)s (Code: %(code)s) [S:%(state)s]",
                {
                    "guild": o_guild.name,
                    "channel": before.channel.name,
                    "code": close_code,
                    "state": state.name.upper() if state else None,
                },
            )
            await self.disconnect_voice_client(o_guild)

            # reconnect if the guild is configured to auto-join.
            if self.server_data[o_guild.id].auto_join_channel is not None:
                # Look for the last channel we were in.
                target_channel = self.get_channel(before.channel.id)
                if not target_channel:
                    # fall back to the configured channel.
                    target_channel = self.server_data[o_guild.id].auto_join_channel

                if not isinstance(
                    target_channel, (discord.VoiceChannel, discord.StageChannel)
                ):
                    log.error(
                        "Cannot use auto-join channel with type: %(type)s  in guild:  %(guild)s",
                        {"type": type(target_channel), "guild": before.channel.guild},
                    )
                    return True

                if not target_channel:
                    log.error(
                        "Cannot find the auto-joined channel, was it deleted?  Guild:  %s",
                        before.channel.guild,
                    )
                    return True

                log.info(
                    "Reconnecting to auto-joined guild on channel:  %s",
                    target_channel,
                )
                try:
                    r_player = await self.get_player(
                        target_channel, create=True, deserialize=True
                    )

                    if r_player.is_stopped:
                        r_player.play()

                except (TypeError, exceptions.PermissionsError):
                    log.warning(
                        "Cannot auto join channel:  %s",
                        before.channel,
                        exc_info=True,
                    )
            return True

        # TODO: If bot has left a server but still had a client, we should kill it.
        # if o_guild is None and before.channel.guild.id in self.players:

        return False

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """
        Event called by discord.py when the bot joins a new guild.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_guild_join
        """
        log.info("Bot has been added to guild: %s", guild.name)

        # Leave guilds if the owner is not a member and configured to do so.
        if self.config.leavenonowners:
            # Get the owner so we can notify them of the leave via DM.
            owner = self._get_owner_member()
            if owner:
                # check for the owner in the guild.
                check = guild.get_member(owner.id)
                if check is None:
                    await guild.leave()
                    log.info(
                        "Left guild '%s' due to bot owner not found.",
                        guild.name,
                    )
                    await self.safe_send_message(
                        owner,
                        Response(
                            _D(
                                "Left `%(guild)s` due to bot owner not being found in it.",
                                None,
                            ),
                            fmt_args={"guild": guild.name},
                        ),
                    )

        log.debug("Creating data folder for guild %s", guild.id)
        self.config.data_path.joinpath(str(guild.id)).mkdir(exist_ok=True)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """
        Event called by discord.py when the bot is removed from a guild or a guild is deleted.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_guild_remove
        """
        log.info("Bot has been removed from guild: %s", guild.name)
        log.debug("Updated guild list:")
        for s in self.guilds:
            log.debug(" - %s", s.name)

        if guild.id in self.players:
            self.players.pop(guild.id).kill()

    async def on_guild_available(self, guild: discord.Guild) -> None:
        """
        Event called by discord.py when a guild becomes available.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_guild_available
        """
        if not self.init_ok:
            return  # Ignore pre-ready events

        log.info('Guild "%s" has become available.', guild.name)

        player = self.get_player_in(guild)

        if player and player.is_paused and player.guild_or_net_unavailable:
            log.debug(
                'Resuming player in "%s" due to availability.',
                guild.name,
            )
            player.guild_or_net_unavailable = False
            player.resume()

        if player:
            player.guild_or_net_unavailable = False

    async def on_guild_unavailable(self, guild: discord.Guild) -> None:
        """
        Event called by discord.py when Discord API says a guild is unavailable.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_guild_unavailable
        """
        if not self.init_ok:
            return  # Ignore pre-ready events.

        log.info('Guild "%s" has become unavailable.', guild.name)

        player = self.get_player_in(guild)

        if player and player.is_playing:
            log.debug(
                'Pausing player in "%s" due to unavailability.',
                guild.name,
            )
            player.pause()

        if player:
            player.guild_or_net_unavailable = True

    async def on_guild_update(
        self, before: discord.Guild, after: discord.Guild
    ) -> None:
        """
        Event called by discord.py when guild properties are updated.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_guild_update
        """
        if log.getEffectiveLevel() <= logging.EVERYTHING:  # type: ignore[attr-defined]
            log.info("Guild update for:  %s", before)
            for name in set(getattr(before, "__slotnames__")):
                a_val = getattr(after, name, None)
                b_val = getattr(before, name, None)
                if b_val != a_val:
                    log.everything(  # type: ignore[attr-defined]
                        "Guild attribute %(attr)s is now: %(new)s  -- Was: %(old)s",
                        {"attr": name, "new": a_val, "old": b_val},
                    )

    async def on_guild_channel_update(
        self, before: GuildMessageableChannels, after: GuildMessageableChannels
    ) -> None:
        """
        Event called by discord.py when a guild channel is updated.
        https://discordpy.readthedocs.io/en/stable/api.html#discord.on_guild_channel_update
        """
        # This allows us to log when certain channel properties are changed.
        # Mostly for information sake at current.
        changes = ""
        if before.name != after.name:
            changes += f" name = {after.name}"
        if isinstance(
            before, (discord.VoiceChannel, discord.StageChannel)
        ) and isinstance(after, (discord.VoiceChannel, discord.StageChannel)):
            # Splitting hairs, but we could pause playback here until voice update later.
            if before.rtc_region != after.rtc_region:
                changes += f" voice-region = {after.rtc_region}"
            if before.bitrate != after.bitrate:
                changes += f" bitrate = {after.bitrate}"
            if before.user_limit != after.user_limit:
                changes += f" user-limit = {after.user_limit}"
        # The chat delay is not currently respected by MusicBot. Is this a problem?
        if before.slowmode_delay != after.slowmode_delay:
            changes += f" slowmode = {after.slowmode_delay}"

        if changes:
            log.info(
                "Channel update for:  %(channel)s  --  %(changes)s",
                {"channel": before, "changes": changes},
            )
import configparser
import datetime
import logging
import os
import pathlib
import shutil
import sys
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Union,
    overload,
)

import configupdater
from configupdater.block import Comment, Space

from . import get_write_base, write_path
from .constants import (
    APL_FILE_HISTORY,
    DATA_FILE_COOKIES,
    DATA_FILE_SERVERS,
    DATA_FILE_YTDLP_OAUTH2,
    DEFAULT_AUDIO_CACHE_DIR,
    DEFAULT_COMMAND_ALIAS_FILE,
    DEFAULT_DATA_DIR,
    DEFAULT_FOOTER_TEXT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOGS_KEPT,
    DEFAULT_LOGS_ROTATE_FORMAT,
    DEFAULT_MEDIA_FILE_DIR,
    DEFAULT_OPTIONS_FILE,
    DEFAULT_PLAYLIST_DIR,
    DEFAULT_SONG_BLOCKLIST_FILE,
    DEFAULT_USER_BLOCKLIST_FILE,
    DEPRECATED_USER_BLACKLIST,
    EXAMPLE_OPTIONS_FILE,
    MAXIMUM_LOGS_LIMIT,
    MUSICBOT_TOKEN_ENV_VAR,
)
from .exceptions import HelpfulError, RetryConfigException
from .i18n import _Dd
from .logs import (
    set_logging_level,
    set_logging_max_kept_logs,
    set_logging_rotate_date_format,
)
from .utils import format_size_from_bytes, format_size_to_bytes, format_time_to_seconds

if TYPE_CHECKING:
    import discord

    from .bot import MusicBot
    from .permissions import Permissions

# Type for ConfigParser.get(... vars) argument
ConfVars = Optional[Mapping[str, str]]
CommentArgs = Optional[Dict[str, Any]]
# Types considered valid for config options.
DebugLevel = Tuple[str, int]
RegTypes = Union[str, int, bool, float, Set[int], Set[str], DebugLevel, pathlib.Path]

log = logging.getLogger(__name__)


def create_file_ifnoexist(
    path: pathlib.Path, content: Optional[Union[str, List[str]]]
) -> None:
    """
    Creates a UTF8 text file at given `path` if it does not exist.
    If supplied, `content` will be used to write initial content to the file.
    """
    if not path.exists():
        with open(path, "w", encoding="utf8") as fh:
            if content and isinstance(content, list):
                fh.writelines(content)
            elif content and isinstance(content, str):
                fh.write(content)
            log.warning("Creating %s", path)


class Config:
    """
    This object is responsible for loading and validating config, using default
    values where needed. It provides interfaces to read and set the state of
    config values, and finally a method to update the config file with values
    from this instance of config.
    """

    def __init__(self, config_file: pathlib.Path) -> None:
        """
        Handles locating, initializing, loading, and validating config data.
        Immediately validates all data which can be without async facilities.

        :param: config_file:  a configuration file path to load.

        :raises: musicbot.exceptions.HelpfulError
            if configuration fails to load for some typically known reason.
        """
        log.info("Loading config from:  %s", config_file)
        self.config_file = config_file
        self.find_config()  # this makes sure the config exists.

        # TODO:  decide on this lil feature.
        # Make updates to config file before loading it in.
        # ConfigRenameManager(self.config_file)

        config = ExtendedConfigParser()
        if self.config_file.is_file():
            config.read(config_file, encoding="utf-8")
        self.register = ConfigOptionRegistry(self, config)

        # DebugLevel is important for feedback, so we load it first.
        self._debug_level: DebugLevel = self.register.init_option(
            section="MusicBot",
            option="DebugLevel",
            dest="_debug_level",
            default=ConfigDefaults._debug_level(),
            getter="getdebuglevel",
            comment=_Dd(
                "Set the log verbosity of MusicBot. Normally this should be set to INFO.\n"
                "It can be set to one of the following:\n"
                " CRITICAL, ERROR, WARNING, INFO, DEBUG, VOICEDEBUG, FFMPEG, NOISY, or EVERYTHING"
            ),
            editable=False,
        )
        self.debug_level_str: str = self._debug_level[0]
        self.debug_level: int = self._debug_level[1]
        self.debug_mode: bool = self.debug_level <= logging.DEBUG
        set_logging_level(self.debug_level)

        # This gets filled in later while checking for token in the environment vars.
        self.auth: Tuple[str] = ("",)

        # Credentials
        self._login_token: str = self.register.init_option(
            section="Credentials",
            option="Token",
            dest="_login_token",
            getter="get",
            default=ConfigDefaults.token,
            comment=_Dd(
                "Discord bot authentication token for your Bot.\n"
                "Visit Discord Developer Portal to create a bot App and generate your Token.\n"
                "Never publish your bot token!"
            ),
            editable=False,
        )

        self.spotify_clientid = self.register.init_option(
            section="Credentials",
            option="Spotify_ClientID",
            dest="spotify_clientid",
            default=ConfigDefaults.spotify_clientid,
            comment=_Dd(
                "Provide your own Spotify Client ID to enable MusicBot to interact with Spotify API.\n"
                "MusicBot will try to use the web player API (guest mode) if nothing is set here.\n"
                "Using your own API credentials grants higher usage limits than guest mode."
            ),
            editable=False,
        )
        self.spotify_clientsecret = self.register.init_option(
            section="Credentials",
            option="Spotify_ClientSecret",
            dest="spotify_clientsecret",
            default=ConfigDefaults.spotify_clientsecret,
            comment=_Dd(
                "Provide your Spotify Client Secret to enable MusicBot to interact with Spotify API.\n"
                "This is required if you set the Spotify_ClientID option above."
            ),
            editable=False,
        )

        # Permissions
        self.owner_id: int = self.register.init_option(
            section="Permissions",
            option="OwnerID",
            dest="owner_id",
            default=ConfigDefaults.owner_id,
            comment=_Dd(
                # TRANSLATORS: 'auto' should not be translated.
                "Provide a Discord User ID number to set the owner of this bot.\n"
                "The word 'auto' or number 0 will set the owner based on App information.\n"
                "Only one owner ID can be set here. Generally, setting 'auto' is recommended."
            ),
            getter="getownerid",
            editable=False,
        )
        self.dev_ids: Set[int] = self.register.init_option(
            section="Permissions",
            option="DevIDs",
            dest="dev_ids",
            default=ConfigDefaults.dev_ids,
            comment=_Dd(
                "A list of Discord User IDs who can use the dev-only commands.\n"
                "Warning: dev-only commands can allow arbitrary remote code execution.\n"
                "Use spaces to separate multiple IDs.\n"
                "Most users should leave this setting blank."
            ),
            getter="getidset",
            editable=False,
        )

        self.bot_exception_ids: Set[int] = self.register.init_option(
            section="Permissions",
            option="BotExceptionIDs",
            dest="bot_exception_ids",
            getter="getidset",
            default=ConfigDefaults.bot_exception_ids,
            comment=_Dd(
                "Discord Member IDs for other bots that MusicBot should not ignore.\n"
                "Use spaces to separate multiple IDs.\n"
                "All bots are ignored by default."
            ),
        )

        # Chat
        self.command_prefix: str = self.register.init_option(
            section="Chat",
            option="CommandPrefix",
            dest="command_prefix",
            default=ConfigDefaults.command_prefix,
            comment=_Dd(
                "Command prefix is how all MusicBot commands must be started in Discord messages.\n"
                "E.g., if you set this to * the play command is trigger by *play ..."
            ),
        )
        self.commands_via_mention: bool = self.register.init_option(
            section="Chat",
            option="CommandsByMention",
            dest="commands_via_mention",
            default=ConfigDefaults.commands_via_mention,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: YourBotNameHere can be translated.  CommandPrefix should not be translated.
                "Enable using commands with @[YourBotNameHere]\n"
                "The CommandPrefix is still available, but can be replaced with @ mention."
            ),
        )
        self.bound_channels: Set[int] = self.register.init_option(
            section="Chat",
            option="BindToChannels",
            dest="bound_channels",
            default=ConfigDefaults.bound_channels,
            getter="getidset",
            comment=_Dd(
                "ID numbers for text channels that MusicBot should exclusively use for commands.\n"
                "This can contain IDs for channels in multiple servers.\n"
                "Use spaces to separate multiple IDs.\n"
                "All channels are used if this is not set."
            ),
        )
        self.unbound_servers: bool = self.register.init_option(
            section="Chat",
            option="AllowUnboundServers",
            dest="unbound_servers",
            default=ConfigDefaults.unbound_servers,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: BindToChannels should not be translated.
                "Allow responses in all channels while no specific channel is set for a server.\n"
                "Only used when BindToChannels is missing an ID for a server."
            ),
        )
        self.autojoin_channels: Set[int] = self.register.init_option(
            section="Chat",
            option="AutojoinChannels",
            dest="autojoin_channels",
            default=ConfigDefaults.autojoin_channels,
            getter="getidset",
            comment=_Dd(
                "A list of Voice Channel IDs that MusicBot should automatically join on start up.\n"
                "Use spaces to separate multiple IDs."
            ),
        )
        self.dm_nowplaying: bool = self.register.init_option(
            section="Chat",
            option="DMNowPlaying",
            dest="dm_nowplaying",
            default=ConfigDefaults.dm_nowplaying,
            getter="getboolean",
            comment=_Dd(
                "MusicBot will try to send Now Playing notices directly to the member who requested the song instead of posting in a server channel."
            ),
        )
        self.no_nowplaying_auto: bool = self.register.init_option(
            section="Chat",
            option="DisableNowPlayingAutomatic",
            dest="no_nowplaying_auto",
            default=ConfigDefaults.no_nowplaying_auto,
            getter="getboolean",
            comment=_Dd(
                "Disable now playing messages for songs played via auto playlist."
            ),
        )
        self.nowplaying_channels: Set[int] = self.register.init_option(
            section="Chat",
            option="NowPlayingChannels",
            dest="nowplaying_channels",
            default=ConfigDefaults.nowplaying_channels,
            getter="getidset",
            comment=_Dd(
                "Forces MusicBot to use a specific channel to send now playing messages.\n"
                "Only one text channel ID can be used per server."
            ),
        )
        self.delete_nowplaying: bool = self.register.init_option(
            section="Chat",
            option="DeleteNowPlaying",
            dest="delete_nowplaying",
            default=ConfigDefaults.delete_nowplaying,
            getter="getboolean",
            comment=_Dd("MusicBot will automatically delete Now Playing messages."),
        )

        self.default_volume: float = self.register.init_option(
            section="MusicBot",
            option="DefaultVolume",
            dest="default_volume",
            default=ConfigDefaults.default_volume,
            getter="getpercent",
            comment=_Dd(
                "Sets the default volume level MusicBot will play songs at.\n"
                "You can use any value from 0 to 1, or 0% to 100% volume."
            ),
        )
        self.default_speed: float = self.register.init_option(
            section="MusicBot",
            option="DefaultSpeed",
            dest="default_speed",
            default=ConfigDefaults.default_speed,
            getter="getfloat",
            comment=_Dd(
                "Sets the default speed MusicBot will play songs at.\n"
                "Must be a value from 0.5 to 100.0 for ffmpeg to use it.\n"
                "A value of 1 is normal playback speed.\n"
                "Note: Streamed media does not support speed adjustments."
            ),
        )
        self.skips_required: int = self.register.init_option(
            section="MusicBot",
            option="SkipsRequired",
            dest="skips_required",
            default=ConfigDefaults.skips_required,
            getter="getint",
            comment=_Dd(
                # TRANSLATORS: SkipRatio should not be translated.
                "Number of channel member votes required to skip a song.\n"
                "Acts as a minimum when SkipRatio would require more votes."
            ),
        )
        self.skip_ratio_required: float = self.register.init_option(
            section="MusicBot",
            option="SkipRatio",
            dest="skip_ratio_required",
            default=ConfigDefaults.skip_ratio_required,
            getter="getpercent",
            comment=_Dd(
                # TRANSLATORS: SkipsRequired is not translated
                "This percent of listeners in voice must vote for skip.\n"
                "If SkipsRequired is lower than the computed value, it will be used instead.\n"
                "You can set this from 0 to 1, or 0% to 100%."
            ),
        )
        self.save_videos: bool = self.register.init_option(
            section="MusicBot",
            option="SaveVideos",
            dest="save_videos",
            default=ConfigDefaults.save_videos,
            getter="getboolean",
            comment=_Dd(
                "Allow MusicBot to keep downloaded media, or delete it right away."
            ),
        )
        self.storage_limit_bytes: int = self.register.init_option(
            section="MusicBot",
            option="StorageLimitBytes",
            dest="storage_limit_bytes",
            default=ConfigDefaults.storage_limit_bytes,
            getter="getdatasize",
            comment=_Dd(
                # TRANSLATORS: SaveVideos is not translated.
                "If SaveVideos is enabled, set a limit on how much storage space should be used."
            ),
        )
        self.storage_limit_days: int = self.register.init_option(
            section="MusicBot",
            option="StorageLimitDays",
            dest="storage_limit_days",
            default=ConfigDefaults.storage_limit_days,
            getter="getint",
            comment=_Dd(
                # TRANSLATORS: SaveVideos should not be translated.
                "If SaveVideos is enabled, set a limit on how long files should be kept."
            ),
        )
        self.storage_retain_autoplay: bool = self.register.init_option(
            section="MusicBot",
            option="StorageRetainAutoPlay",
            dest="storage_retain_autoplay",
            default=ConfigDefaults.storage_retain_autoplay,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: SaveVideos should not be translated.
                "If SaveVideos is enabled, never purge auto playlist songs from the cache regardless of limits."
            ),
        )
        self.now_playing_mentions: bool = self.register.init_option(
            section="MusicBot",
            option="NowPlayingMentions",
            dest="now_playing_mentions",
            default=ConfigDefaults.now_playing_mentions,
            getter="getboolean",
            comment=_Dd("Mention the user who added the song when it is played."),
        )
        self.auto_summon: bool = self.register.init_option(
            section="MusicBot",
            option="AutoSummon",
            dest="auto_summon",
            default=ConfigDefaults.auto_summon,
            getter="getboolean",
            comment=_Dd(
                "Automatically join the owner if they are in an accessible voice channel when bot starts."
            ),
        )
        self.auto_playlist: bool = self.register.init_option(
            section="MusicBot",
            option="UseAutoPlaylist",
            dest="auto_playlist",
            default=ConfigDefaults.auto_playlist,
            getter="getboolean",
            comment=_Dd(
                "Enable MusicBot to automatically play music from the auto playlist when the queue is empty."
            ),
        )
        self.auto_playlist_random: bool = self.register.init_option(
            section="MusicBot",
            option="AutoPlaylistRandom",
            dest="auto_playlist_random",
            default=ConfigDefaults.auto_playlist_random,
            getter="getboolean",
            comment=_Dd("Shuffles the auto playlist tracks before playing them."),
        )
        self.auto_playlist_autoskip: bool = self.register.init_option(
            section="MusicBot",
            option="AutoPlaylistAutoSkip",
            dest="auto_playlist_autoskip",
            default=ConfigDefaults.auto_playlist_autoskip,
            getter="getboolean",
            comment=_Dd(
                "Enable automatic skip of auto playlist songs when a user plays a new song.\n"
                "This only applies to the current playing song if it was added by the auto playlist."
            ),
        )
        self.auto_playlist_remove_on_block: bool = self.register.init_option(
            section="MusicBot",
            option="AutoPlaylistRemoveBlocked",
            dest="auto_playlist_remove_on_block",
            default=ConfigDefaults.auto_playlist_remove_on_block,
            getter="getboolean",
            comment=_Dd(
                "Remove songs from the auto playlist if they are found in the song block list."
            ),
        )
        self.auto_pause: bool = self.register.init_option(
            section="MusicBot",
            option="AutoPause",
            dest="auto_pause",
            default=ConfigDefaults.auto_pause,
            getter="getboolean",
            comment="MusicBot will automatically pause playback when no users are listening.",
        )
        self.delete_messages: bool = self.register.init_option(
            section="MusicBot",
            option="DeleteMessages",
            dest="delete_messages",
            default=ConfigDefaults.delete_messages,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: DeleteDelayShort and DeleteDelayLong should not be translated.
                "Allow MusicBot to automatically delete messages it sends, after a delay.\n"
                "Delay period is controlled by DeleteDelayShort and DeleteDelayLong."
            ),
        )
        self.delete_invoking: bool = self.register.init_option(
            section="MusicBot",
            option="DeleteInvoking",
            dest="delete_invoking",
            default=ConfigDefaults.delete_invoking,
            getter="getboolean",
            comment=_Dd("Auto delete valid commands after a delay."),
        )
        self.delete_delay_short: float = self.register.init_option(
            section="MusicBot",
            option="DeleteDelayShort",
            dest="delete_invoking",
            default=ConfigDefaults.delete_delay_short,
            getter="getduration",
            comment=_Dd(
                "Sets the short period of seconds before deleting messages.\n"
                "This period is used by messages that require no further interaction."
            ),
        )
        self.delete_delay_long: float = self.register.init_option(
            section="MusicBot",
            option="DeleteDelayLong",
            dest="delete_invoking",
            default=ConfigDefaults.delete_delay_long,
            getter="getduration",
            comment=_Dd(
                "Sets the long delay period before deleting messages.\n"
                "This period is used by interactive or long-winded messages, like search and help."
            ),
        )

        self.persistent_queue: bool = self.register.init_option(
            section="MusicBot",
            option="PersistentQueue",
            dest="persistent_queue",
            default=ConfigDefaults.persistent_queue,
            getter="getboolean",
            comment=_Dd(
                "Allow MusicBot to save the song queue, so queued songs will survive restarts."
            ),
        )
        self.pre_download_next_song: bool = self.register.init_option(
            section="MusicBot",
            option="PreDownloadNextSong",
            dest="pre_download_next_song",
            default=ConfigDefaults.pre_download_next_song,
            getter="getboolean",
            comment=_Dd(
                "Enable MusicBot to download the next song in the queue while a song is playing.\n"
                "Currently this option does not apply to auto playlist or songs added to an empty queue."
            ),
        )
        self.status_message: str = self.register.init_option(
            section="MusicBot",
            option="StatusMessage",
            dest="status_message",
            default=ConfigDefaults.status_message,
            comment=_Dd(
                "Specify a custom message to use as the bot's status. If left empty, the bot\n"
                "will display dynamic info about music currently being played in its status instead.\n"
                "Status messages may also use the following variables:\n"
                " {n_playing}   = Number of currently Playing music players.\n"
                " {n_paused}    = Number of currently Paused music players.\n"
                " {n_connected} = Number of connected music players, in any player state.\n"
                "\n"
                "The following variables give access to information about the player and track.\n"
                "These variables may not be accurate in multi-guild bots:\n"
                " {p0_length}   = The total duration of the track, if available. Ex: [2:34]\n"
                " {p0_title}    = The track title for the currently playing track.\n"
                " {p0_url}      = The track URL for the currently playing track."
            ),
        )
        self.status_include_paused: bool = self.register.init_option(
            section="MusicBot",
            option="StatusIncludePaused",
            dest="status_include_paused",
            default=ConfigDefaults.status_include_paused,
            getter="getboolean",
            comment=_Dd(
                "If enabled, status messages will report info on paused players."
            ),
        )
        self.write_current_song: bool = self.register.init_option(
            section="MusicBot",
            option="WriteCurrentSong",
            dest="write_current_song",
            default=ConfigDefaults.write_current_song,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: [Server ID] is a descriptive placeholder and may be translated.
                "If enabled, MusicBot will save the track title to:  data/[Server ID]/current.txt"
            ),
        )
        self.allow_author_skip: bool = self.register.init_option(
            section="MusicBot",
            option="AllowAuthorSkip",
            dest="allow_author_skip",
            default=ConfigDefaults.allow_author_skip,
            getter="getboolean",
            comment=_Dd(
                "Allow the member who requested the song to skip it, bypassing votes."
            ),
        )
        self.use_experimental_equalization: bool = self.register.init_option(
            section="MusicBot",
            option="UseExperimentalEqualization",
            dest="use_experimental_equalization",
            default=ConfigDefaults.use_experimental_equalization,
            getter="getboolean",
            comment=_Dd(
                "Tries to use ffmpeg to get volume normalizing options for use in playback.\n"
                "This option can cause delay between playing songs, as the whole track must be processed."
            ),
        )
        self.embeds: bool = self.register.init_option(
            section="MusicBot",
            option="UseEmbeds",
            dest="embeds",
            default=ConfigDefaults.embeds,
            getter="getboolean",
            comment=_Dd("Allow MusicBot to format its messages as embeds."),
        )
        self.queue_length: int = self.register.init_option(
            section="MusicBot",
            option="QueueLength",
            dest="queue_length",
            default=ConfigDefaults.queue_length,
            getter="getint",
            comment=_Dd(
                "The number of entries to show per-page when using q command to list the queue."
            ),
        )
        self.remove_ap: bool = self.register.init_option(
            section="MusicBot",
            option="RemoveFromAPOnError",
            dest="remove_ap",
            default=ConfigDefaults.remove_ap,
            getter="getboolean",
            comment=_Dd(
                "Enable MusicBot to automatically remove unplayable entries from the auto playlist."
            ),
        )
        self.show_config_at_start: bool = self.register.init_option(
            section="MusicBot",
            option="ShowConfigOnLaunch",
            dest="show_config_at_start",
            default=ConfigDefaults.show_config_at_start,
            getter="getboolean",
            comment=_Dd("Display MusicBot config settings in the logs at startup."),
        )
        self.legacy_skip: bool = self.register.init_option(
            section="MusicBot",
            option="LegacySkip",
            dest="legacy_skip",
            default=ConfigDefaults.legacy_skip,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: InstaSkip should not be translated.
                "Enable users with the InstaSkip permission to bypass skip voting and force skips."
            ),
        )
        self.leavenonowners: bool = self.register.init_option(
            section="MusicBot",
            option="LeaveServersWithoutOwner",
            dest="leavenonowners",
            default=ConfigDefaults.leavenonowners,
            getter="getboolean",
            comment=_Dd(
                "If enabled, MusicBot will leave servers if the owner is not in their member list."
            ),
        )
        self.usealias: bool = self.register.init_option(
            section="MusicBot",
            option="UseAlias",
            dest="usealias",
            default=ConfigDefaults.usealias,
            getter="getboolean",
            comment=_Dd(
                "If enabled, MusicBot will allow commands to have multiple names using data in:  config/aliases.json"
            ),
            comment_args={"filepath": DEFAULT_COMMAND_ALIAS_FILE},
        )
        self.footer_text: str = self.register.init_option(
            section="MusicBot",
            option="CustomEmbedFooter",
            dest="footer_text",
            default=ConfigDefaults.footer_text,
            comment=_Dd(
                # TRANSLATORS: UseEmbeds should not be translated.
                "Replace MusicBot name/version in embed footer with custom text.\n"
                "Only applied when UseEmbeds is enabled and it is not blank."
            ),
            default_is_empty=True,
        )
        self.remove_embed_footer: bool = self.register.init_option(
            section="MusicBot",
            option="RemoveEmbedFooter",
            dest="remove_embed_footer",
            default=ConfigDefaults.remove_embed_footer,
            getter="getboolean",
            comment=_Dd("Completely remove the footer from embeds."),
        )
        self.self_deafen: bool = self.register.init_option(
            section="MusicBot",
            option="SelfDeafen",
            dest="self_deafen",
            default=ConfigDefaults.self_deafen,
            getter="getboolean",
            comment=_Dd(
                "MusicBot will automatically deafen itself when entering a voice channel."
            ),
        )
        self.leave_inactive_channel: bool = self.register.init_option(
            section="MusicBot",
            option="LeaveInactiveVC",
            dest="leave_inactive_channel",
            default=ConfigDefaults.leave_inactive_channel,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: LeaveInactiveVCTimeOut should not be translated.
                "If enabled, MusicBot will leave a voice channel when no users are listening,\n"
                "after waiting for a period set in LeaveInactiveVCTimeOut option.\n"
                "Listeners are channel members, excluding bots, who are not deafened."
            ),
        )
        self.leave_inactive_channel_timeout: float = self.register.init_option(
            section="MusicBot",
            option="LeaveInactiveVCTimeOut",
            dest="leave_inactive_channel_timeout",
            default=ConfigDefaults.leave_inactive_channel_timeout,
            getter="getduration",
            comment=_Dd(
                "Set a period of time to wait before leaving an inactive voice channel.\n"
                "You can set this to a number of seconds or phrase like:  4 hours"
            ),
        )
        self.leave_after_queue_empty: bool = self.register.init_option(
            section="MusicBot",
            option="LeaveAfterQueueEmpty",
            dest="leave_after_queue_empty",
            default=ConfigDefaults.leave_after_queue_empty,
            getter="getboolean",
            comment=_Dd(
                "If enabled, MusicBot will leave the channel immediately when the song queue is empty."
            ),
        )
        self.leave_player_inactive_for: float = self.register.init_option(
            section="MusicBot",
            option="LeavePlayerInactiveFor",
            dest="leave_player_inactive_for",
            default=ConfigDefaults.leave_player_inactive_for,
            getter="getduration",
            comment=_Dd(
                "When paused or no longer playing, wait for this amount of time then leave voice.\n"
                "You can set this to a number of seconds of phrase like:  15 minutes\n"
                "Set it to 0 to disable leaving in this way."
            ),
        )
        self.searchlist: bool = self.register.init_option(
            section="MusicBot",
            option="SearchList",
            dest="searchlist",
            default=ConfigDefaults.searchlist,
            getter="getboolean",
            comment=_Dd(
                "If enabled, users must indicate search result choices by sending a message instead of using reactions."
            ),
        )
        self.defaultsearchresults: int = self.register.init_option(
            section="MusicBot",
            option="DefaultSearchResults",
            dest="defaultsearchresults",
            default=ConfigDefaults.defaultsearchresults,
            getter="getint",
            comment=_Dd(
                "Sets the default number of search results to fetch when using the search command without a specific number."
            ),
        )

        self.enable_options_per_guild: bool = self.register.init_option(
            section="MusicBot",
            option="EnablePrefixPerGuild",
            dest="enable_options_per_guild",
            default=ConfigDefaults.enable_options_per_guild,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: setprefix should not be translated.
                "Allow MusicBot to save a per-server command prefix, and enables the setprefix command."
            ),
        )

        self.round_robin_queue: bool = self.register.init_option(
            section="MusicBot",
            option="RoundRobinQueue",
            dest="round_robin_queue",
            default=ConfigDefaults.defaultround_robin_queue,
            getter="getboolean",
            comment=_Dd(
                "If enabled and multiple members are adding songs, MusicBot will organize playback for one song per member."
            ),
        )

        self.enable_network_checker: bool = self.register.init_option(
            section="MusicBot",
            option="EnableNetworkChecker",
            dest="enable_network_checker",
            default=ConfigDefaults.enable_network_checker,
            getter="getboolean",
            comment=_Dd(
                "Allow MusicBot to use timed pings to detect network outage and availability.\n"
                "This may be useful if you keep the bot joined to a channel or playing music 24/7.\n"
                "MusicBot must be restarted to enable network testing.\n"
                "By default this is disabled."
            ),
        )

        # write_path not needed, used for display only.
        hist_file = pathlib.Path(DEFAULT_PLAYLIST_DIR).joinpath(APL_FILE_HISTORY)
        self.enable_queue_history_global: bool = self.register.init_option(
            section="MusicBot",
            option="SavePlayedHistoryGlobal",
            dest="enable_queue_history_global",
            default=ConfigDefaults.enable_queue_history_global,
            getter="getboolean",
            comment=_Dd(
                "Enable saving all songs played by MusicBot to a global playlist file:  %(filename)s\n"
                "This will contain all songs from all servers."
            ),
            comment_args={"filename": hist_file},
        )
        self.enable_queue_history_guilds: bool = self.register.init_option(
            section="MusicBot",
            option="SavePlayedHistoryGuilds",
            dest="enable_queue_history_guilds",
            default=ConfigDefaults.enable_queue_history_guilds,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS:  [Server ID] is a descriptive placeholder, and can be translated.
                "Enable saving songs played per-server to a playlist file:  %(basename)s[Server ID]%(ext)s"
            ),
            comment_args={
                "basename": hist_file.with_name(hist_file.stem),
                "ext": hist_file.suffix,
            },
        )

        self.enable_local_media: bool = self.register.init_option(
            section="MusicBot",
            option="EnableLocalMedia",
            dest="enable_local_media",
            default=ConfigDefaults.enable_local_media,
            getter="getboolean",
            comment=_Dd(
                # TRANSLATORS: MediaFileDirectory should not be translated.
                "Enable playback of local media files using the play command.\n"
                "When enabled, users can use:  `play file://path/to/file.ext`\n"
                "to play files from the local MediaFileDirectory path."
            ),
        )

        self.auto_unpause_on_play: bool = self.register.init_option(
            section="MusicBot",
            option="UnpausePlayerOnPlay",
            dest="auto_unpause_on_play",
            default=ConfigDefaults.auto_unpause_on_play,
            getter="getboolean",
            comment=_Dd(
                "Allow MusicBot to automatically unpause when play commands are used."
            ),
        )

        # This is likely to turn into one option for each separate part.
        # Due to how the support for protocols differs from part to part.
        # ytdlp has its own option that uses requests.
        # aiohttp requires per-call proxy parameter be set.
        # and ffmpeg with stream mode also makes its own direct connections.
        # top it off with proxy for the API. Once we tip the proxy iceberg...
        # In some cases, users might get away with setting environment variables,
        # HTTP_PROXY, HTTPS_PROXY, and others for ytdlp and ffmpeg.
        # While aiohttp would require some other param or config file for that.
        self.ytdlp_proxy: str = self.register.init_option(
            section="MusicBot",
            option="YtdlpProxy",
            dest="ytdlp_proxy",
            default=ConfigDefaults.ytdlp_proxy,
            comment=_Dd(
                "Experimental, HTTP/HTTPS proxy settings to use with ytdlp media downloader.\n"
                "The value set here is passed to `ytdlp --proxy` and aiohttp header checking.\n"
                "Leave blank to disable."
            ),
        )
        self.ytdlp_user_agent: str = self.register.init_option(
            section="MusicBot",
            option="YtdlpUserAgent",
            dest="ytdlp_user_agent",
            default=ConfigDefaults.ytdlp_user_agent,
            comment=_Dd(
                "Experimental option to set a static User-Agent header in yt-dlp.\n"
                "It is not typically recommended by yt-dlp to change the UA string.\n"
                "For examples of what you might put here, check the following two links:\n"
                "   https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/User-Agent \n"
                "   https://www.useragents.me/ \n"
                "Leave blank to use default, dynamically generated UA strings."
            ),
        )
        self.ytdlp_use_oauth2: bool = self.register.init_option(
            section="MusicBot",
            option="YtdlpUseOAuth2",
            dest="ytdlp_use_oauth2",
            default=ConfigDefaults.ytdlp_use_oauth2,
            getter="getboolean",
            comment=_Dd(
                "Experimental option to enable yt-dlp to use a YouTube account via OAuth2.\n"
                "When enabled, you must use the generated URL and code to authorize an account.\n"
                "The authorization token is then stored in the "
                "`%(oauthfile)s` file.\n"
                "This option should not be used when cookies are enabled.\n"
                "Using a personal account may not be recommended.\n"
                "Set yes to enable or no to disable."
            ),
            comment_args={"oauthfile": f"{DEFAULT_DATA_DIR}/{DATA_FILE_YTDLP_OAUTH2}"},
        )
        self.ytdlp_oauth2_url: str = self.register.init_option(
            section="MusicBot",
            option="YtdlpOAuth2URL",
            dest="ytdlp_oauth2_url",
            getter="getstr",
            default=ConfigDefaults.ytdlp_oauth2_url,
            comment=_Dd(
                "Optional YouTube video URL used at start-up for triggering OAuth2 authorization.\n"
                "This starts the OAuth2 prompt early, rather than waiting for a song request.\n"
                "The URL set here should be an accessible YouTube video URL.\n"
                "Authorization must be completed before start-up will continue when this is set."
            ),
        )
        # Was: [Credentials] >> YtdlpOAuth2ClientID
        self.ytdlp_oauth2_client_id: str = ConfigDefaults.ytdlp_oauth2_client_id
        # Was: Credentials] >> YtdlpOAuth2ClientSecret
        self.ytdlp_oauth2_client_secret: str = ConfigDefaults.ytdlp_oauth2_client_secret

        # Files
        self.user_blocklist_enabled: bool = self.register.init_option(
            section="MusicBot",
            option="EnableUserBlocklist",
            dest="user_blocklist_enabled",
            default=ConfigDefaults.user_blocklist_enabled,
            getter="getboolean",
            comment=_Dd(
                "Toggle the user block list feature, without emptying the block list."
            ),
        )
        self.user_blocklist_file: pathlib.Path = self.register.init_option(
            section="Files",
            option="UserBlocklistFile",
            dest="user_blocklist_file",
            default=ConfigDefaults.user_blocklist_file,
            getter="getpathlike",
            comment=_Dd(
                "An optional file path to a text file listing Discord User IDs, one per line."
            ),
            default_is_empty=True,
        )
        self.user_blocklist: UserBlocklist = UserBlocklist(self.user_blocklist_file)

        self.song_blocklist_enabled: bool = self.register.init_option(
            section="MusicBot",
            option="EnableSongBlocklist",
            dest="song_blocklist_enabled",
            default=ConfigDefaults.song_blocklist_enabled,
            getter="getboolean",
            comment=_Dd(
                "Enable the song block list feature, without emptying the block list."
            ),
        )
        self.song_blocklist_file: pathlib.Path = self.register.init_option(
            section="Files",
            option="SongBlocklistFile",
            dest="song_blocklist_file",
            default=ConfigDefaults.song_blocklist_file,
            getter="getpathlike",
            comment=_Dd(
                "An optional file path to a text file that lists URLs, words, or phrases one per line.\n"
                "Any song title or URL that contains any line in the list will be blocked."
            ),
            default_is_empty=True,
        )
        self.song_blocklist: SongBlocklist = SongBlocklist(self.song_blocklist_file)

        self.auto_playlist_dir: pathlib.Path = self.register.init_option(
            section="Files",
            option="AutoPlaylistDirectory",
            dest="auto_playlist_dir",
            default=ConfigDefaults.auto_playlist_dir,
            getter="getpathlike",
            comment=_Dd(
                "An optional path to a directory containing auto playlist files.\n"
                "Each file should contain a list of playable URLs or terms, one track per line."
            ),
            default_is_empty=True,
        )

        self.media_file_dir: pathlib.Path = self.register.init_option(
            section="Files",
            option="MediaFileDirectory",
            dest="media_file_dir",
            default=ConfigDefaults.media_file_dir,
            getter="getpathlike",
            comment=_Dd(
                "An optional directory path where playable media files can be stored.\n"
                "All files and sub-directories can then be accessed by using 'file://' as a protocol.\n"
                "Example:  file://some/folder/name/file.ext\n"
                "Maps to:  %(path)s/some/folder/name/file.ext"
            ),
            comment_args={"path": "./media"},
            default_is_empty=True,
        )

        # TODO: add options for default language(s)
        # at least one for guild output language default.
        # log lang may be better off set via CLI / ENV.

        self.audio_cache_path: pathlib.Path = self.register.init_option(
            section="Files",
            option="AudioCachePath",
            dest="audio_cache_path",
            default=ConfigDefaults.audio_cache_path,
            getter="getpathlike",
            comment=_Dd(
                "An optional directory path where MusicBot will store long and short-term cache for playback."
            ),
            default_is_empty=True,
        )

        self.logs_max_kept: int = self.register.init_option(
            section="Files",
            option="LogsMaxKept",
            dest="logs_max_kept",
            default=ConfigDefaults.logs_max_kept,
            getter="getint",
            comment=_Dd(
                "Configure automatic log file rotation at restart, and limit the number of files kept.\n"
                "When disabled, only one log is kept and its contents are replaced each run.\n"
                "Set to 0 to disable.  Maximum allowed number is %(max)s."
            ),
            comment_args={"max": MAXIMUM_LOGS_LIMIT},
        )

        self.logs_date_format: str = self.register.init_option(
            section="Files",
            option="LogsDateFormat",
            dest="logs_date_format",
            default=ConfigDefaults.logs_date_format,
            comment=_Dd(
                "Configure the log file date format used when LogsMaxKept is enabled.\n"
                "If left blank, a warning is logged and the default will be used instead.\n"
                "Learn more about time format codes from the tables and data here:\n"
                "    https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior"
            ),
        )

        self.use_opus_probe: bool = self.register.init_option(
            section="MusicBot",
            option="UseOpusAudio",
            dest="use_opus_probe",
            default=ConfigDefaults.use_opus_probe,
            getter="getboolean",
            comment=_Dd(
                "Potentially reduces CPU usage, but disables volume and speed controls.\n"
                "This option will disable UseExperimentalEqualization option as well."
            ),
        )

        #
        # end of config registry.
        #

        if not self.config_file.is_file():
            log.info("Generating new config options files...")
            try:
                ex_file = write_path(EXAMPLE_OPTIONS_FILE)
                self.register.write_default_ini(ex_file)
                shutil.copy(ex_file, self.config_file)
                raise RetryConfigException()
            except OSError as e:
                # pylint: disable=duplicate-code
                raise HelpfulError(
                    # fmt: off
                    "Error creating default config options file.\n"
                    "\n"
                    "Problem:\n"
                    "  MusicBot attempted to generate the config files but failed due to an error:\n"
                    "  %(raw_error)s\n"
                    "\n"
                    "Solution:\n"
                    "  Make sure MusicBot can read and write to your config files.\n",
                    # fmt: on
                    fmt_args={"raw_error": e},
                ) from e
                # pylint: enable=duplicate-code

        # Convert all path constants into config as pathlib.Path objects.
        self.data_path = write_path(DEFAULT_DATA_DIR)
        self.server_names_path = self.data_path.joinpath(DATA_FILE_SERVERS)
        self.cookies_path = self.data_path.joinpath(DATA_FILE_COOKIES)
        self.disabled_cookies_path = self.cookies_path.parent.joinpath(
            f"_{self.cookies_path.name}"
        )
        self.audio_cache_path = self.audio_cache_path.absolute()

        # Validate the config settings match destination values.
        self.register.validate_register_destinations()

        # Make the registry check for missing data in the INI file.
        self.register.update_missing_config()

        if self.register.ini_missing_sections:
            sections_str = ", ".join(
                [f"[{s}]" for s in self.register.ini_missing_sections]
            )
            raise HelpfulError(
                # fmt: off
                "Error while reading config.\n"
                "\n"
                "Problem:\n"
                "  One or more required config option sections are missing.\n"
                "  The missing sections are:\n"
                "  %(sections)s\n"
                "\n"
                "Solution:\n"
                "  Repair your config options file.\n"
                "  Each [Section] must appear only once, with no other text on the same line.\n"
                "  Each section must have at least one option.\n"
                "  Use the example options as a template or copy it from the repository.",
                # fmt: on
                fmt_args={"sections": sections_str},
            )

        # This value gets set dynamically, based on success with API authentication.
        self.spotify_enabled = False

        self.run_checks()

    def run_checks(self) -> None:
        """
        Validation and some sanity check logic for bot settings.

        :raises: musicbot.exceptions.HelpfulError
            if some validation failed that the user needs to correct.
        """
        if self.logs_max_kept > MAXIMUM_LOGS_LIMIT:
            log.warning(
                "Cannot store more than %s log files. Option LogsMaxKept will be limited instead.",
                MAXIMUM_LOGS_LIMIT,
            )
            self.logs_max_kept = MAXIMUM_LOGS_LIMIT
        set_logging_max_kept_logs(self.logs_max_kept)

        if not self.logs_date_format and self.logs_max_kept > 0:
            log.warning(
                "Config option LogsDateFormat is empty and this will break log file rotation. Using default instead."
            )
            self.logs_date_format = DEFAULT_LOGS_ROTATE_FORMAT
        set_logging_rotate_date_format(self.logs_date_format)

        if self.audio_cache_path:
            try:
                acpath = self.audio_cache_path
                if acpath.is_file():
                    raise HelpfulError(
                        # fmt: off
                        "Error while validating config options.\n"
                        "\n"
                        "Problem:\n"
                        "  Config option AudioCachePath is not a directory.\n"
                        "\n"
                        "Solution:\n"
                        "  Make sure the path you configured is a path to a folder / directory."
                        # fmt: on
                    )
                # Might as well test for multiple issues here since we can give feedback.
                if not acpath.is_dir():
                    acpath.mkdir(parents=True, exist_ok=True)
                actest = acpath.joinpath(".bot-test-write")
                actest.touch(exist_ok=True)
                actest.unlink(missing_ok=True)
            except OSError as e:
                log.exception(
                    "An exception was thrown while validating AudioCachePath."
                )
                raise HelpfulError(
                    # fmt: off
                    "Error while validating config options.\n"
                    "\n"
                    "Problem:\n"
                    "  AudioCachePath config option could not be set due to an error:\n"
                    "  %(raw_error)s\n"
                    "\n"
                    "Solution:\n"
                    "  Double check the setting is a valid, accessible directory path.",
                    # fmt: on
                    fmt_args={"raw_error": e},
                ) from e

        log.info("Audio Cache will be stored in:  %s", self.audio_cache_path)

        if not self._login_token:
            # Attempt to fallback to an environment variable.
            env_token = os.environ.get(MUSICBOT_TOKEN_ENV_VAR)
            if env_token:
                self._login_token = env_token
                self.auth = (self._login_token,)
            else:
                raise HelpfulError(
                    # fmt: off
                    "Error while reading config options.\n"
                    "\n"
                    "Problem:\n"
                    "  No bot Token was specified in the config options or environment.\n"
                    "\n"
                    "Solution:\n"
                    "  Set the Token config option or set environment variable %(env_var)s with an App token.",
                    # fmt: on
                    fmt_args={"env_var": MUSICBOT_TOKEN_ENV_VAR},
                )

        else:
            self.auth = (self._login_token,)

        if self.spotify_clientid and self.spotify_clientsecret:
            self.spotify_enabled = True

        self.delete_invoking = self.delete_invoking and self.delete_messages

        if self.status_message and len(self.status_message) > 128:
            log.warning(
                "StatusMessage config option is too long, it will be limited to 128 characters."
            )
            self.status_message = self.status_message[:128]

        if not self.footer_text:
            self.footer_text = ConfigDefaults.footer_text

        if self.default_speed < 0.5 or self.default_speed > 100.0:
            log.warning(
                "The default playback speed must be between 0.5 and 100.0. "
                "The option value of %.3f will be limited instead."
            )
            self.default_speed = max(min(self.default_speed, 100.0), 0.5)

        if self.enable_local_media and not self.media_file_dir.is_dir():
            self.media_file_dir.mkdir(exist_ok=True)

        if self.cookies_path.is_file():
            log.warning(
                "Cookies TXT file detected. MusicBot will pass them to yt-dlp.\n"
                "Cookies are not recommended, may not be supported, and may totally break.\n"
                "Copying cookies from your web-browser risks exposing personal data and \n"
                "in the best case can result in your accounts being banned!\n\n"
                "You have been warned!  Good Luck!  \U0001F596\n"
            )
            # make sure the user sees this.
            time.sleep(3)

    async def async_validate(self, bot: "MusicBot") -> None:
        """
        Validation logic for bot settings that depends on data from async services.

        :raises: musicbot.exceptions.HelpfulError
            if some validation failed that the user needs to correct.

        :raises: RuntimeError if there is a failure in async service data.
        """
        log.debug("Validating options with service data...")

        # attempt to get the owner ID from app-info.
        if self.owner_id == 0:
            if bot.cached_app_info:
                self.owner_id = bot.cached_app_info.owner.id
                log.debug("Acquired owner ID via API")
            else:
                raise HelpfulError(
                    # fmt: off
                    "Error while fetching 'OwnerID' automatically.\n"
                    "\n"
                    "Problem:\n"
                    "  Discord App info is not available.\n"
                    "  This could be a temporary API outage or a bug.\n"
                    "\n"
                    "Solution:\n"
                    "  Manually set the 'OwnerID' config option or try again later."
                    # fmt: on
                )

        if not bot.user:
            log.critical("MusicBot does not have a user instance, cannot proceed.")
            raise RuntimeError("This cannot continue.")

        if self.owner_id == bot.user.id:
            raise HelpfulError(
                # fmt: off
                "Error validating config options.\n"
                "\n"
                "Problem:\n"
                "  The 'OwnerID' config is the same as your Bot / App ID.\n"
                "\n"
                "Solution:\n"
                "  Do not use the Bot or App ID in the 'OwnerID' field."
                # fmt: on
            )

    def find_config(self) -> None:
        """
        Handle locating or initializing a config file, using a previously set
        config file path.
        If the config file is not found, this will check for a file with `.ini` suffix.
        If neither of the above are found, this will attempt to copy the example config.

        :raises: musicbot.exceptions.HelpfulError
            if config fails to be located or has not been configured.
        """
        config = ExtendedConfigParser()

        # Check for options.ini and copy example ini if missing.
        if not self.config_file.is_file():
            log.warning("Config options file not found. Checking for alternatives...")

            example_file = write_path(EXAMPLE_OPTIONS_FILE)
            try:
                # Check for options.ini.ini because windows.
                ini_file = self.config_file.with_suffix(".ini.ini")
                if sys.platform == "nt" and ini_file.is_file():
                    # shutil.move in 3.8 expects str and not path-like.
                    if sys.version_info >= (3, 9):
                        shutil.move(ini_file, self.config_file)
                    else:
                        shutil.move(str(ini_file), str(self.config_file))
                    log.warning(
                        "Renaming %(ini_file)s to %(option_file)s, you should probably turn file extensions on.",
                        {"ini_file": ini_file, "option_file": self.config_file},
                    )

                # Look for an existing examples file.
                elif os.path.isfile(example_file):
                    shutil.copy(example_file, self.config_file)
                    log.warning(
                        "Copying existing example options file:  %(example_file)s",
                        {"example_file": example_file},
                    )

                # Tell the user we don't have any config to use.
                else:
                    log.error(
                        "Could not locate config options or example options files.\n"
                        "MusicBot will generate the config files at the location:\n"
                        "  %(cfg_file)s",
                        {"cfg_file": self.config_file.parent},
                    )
            except OSError as e:
                log.exception(
                    "Something went wrong while trying to find a config option file."
                )
                raise HelpfulError(
                    # fmt: off
                    "Error locating config.\n"
                    "\n"
                    "Problem:\n"
                    "  Could not find or create a config file due to an error:\n"
                    "  %(raw_error)s\n"
                    "\n"
                    "Solution:\n"
                    "  Verify the config folder and files exist and can be read by MusicBot.",
                    # fmt: on
                    fmt_args={"raw_error": e},
                ) from e

        # try to read / parse the config file.
        try:
            config.read(self.config_file, encoding="utf-8")
        except (OSError, configparser.Error) as e:
            raise HelpfulError(
                # fmt: off
                "Error loading config.\n"
                "\n"
                "Problem:\n"
                "  MusicBot could not read config file due to an error:\n"
                "  %(raw_error)s\n"
                "\n"
                "Solution:\n"
                "  Make sure the file is accessible and error free.\n"
                "  Copy the example file from the repo if all else fails.",
                # fmg: on
                fmt_args={"raw_error": e},
            ) from e

    def update_option(self, option: "ConfigOption", value: str) -> bool:
        """
        Uses option data to parse the given value and update its associated config.
        No data is saved to file however.
        """
        tmp_parser = ExtendedConfigParser()
        tmp_parser.read_dict({option.section: {option.option: value}})

        try:
            get = getattr(tmp_parser, option.getter, None)
            if not get:
                log.critical("Dev Bug! Config option has getter that is not available.")
                return False
            new_conf_val = get(option.section, option.option, fallback=option.default)
            if not isinstance(new_conf_val, type(option.default)):
                log.error(
                    "Dev Bug! Config option has invalid type, getter and default must be the same type."
                )
                return False
            setattr(self, option.dest, new_conf_val)
            return True
        except (HelpfulError, ValueError, TypeError):
            return False

    def save_option(self, option: "ConfigOption") -> bool:
        """
        Converts the current Config value into an INI file value as needed.
        Note: ConfigParser must not use multi-line values. This will break them.
        """
        try:
            cu = configupdater.ConfigUpdater()
            cu.optionxform = str  # type: ignore
            cu.read(self.config_file, encoding="utf8")

            if option.section in list(cu.keys()):
                if option.option not in list(cu[option.section].keys()):
                    log.debug("Option was missing previously.")
                    cu[option.section][option.option] = self.register.to_ini(option)
                    c_bits = option.comment.split("\n")
                    adder = cu[option.section][option.option].add_before
                    adder.space()
                    if len(c_bits) > 1:
                        for line in c_bits:
                            adder.comment(line)
                    else:
                        adder.comment(option.comment)
                    cu[option.section][option.option].add_after.space()
                else:
                    cu[option.section][option.option] = self.register.to_ini(option)
            else:
                log.error(
                    "Config section not in parsed config! Missing: %s", option.section
                )
                return False
            cu.update_file()
            log.info(
                "Saved config option: %(config)s  =  %(value)s",
                {
                    "config": option,
                    "value": cu[option.section][option.option].value,
                },
            )
            return True
        except (
            OSError,
            AttributeError,
            configparser.DuplicateSectionError,
            configparser.ParsingError,
        ):
            log.exception("Failed to save config:  %s", option)
            return False


class ConfigDefaults:
    """
    This class contains default values used mainly as config fallback values.
    None type is not allowed as a default value.
    """

    owner_id: int = 0
    token: str = ""
    dev_ids: Set[int] = set()
    bot_exception_ids: Set[int] = set()

    spotify_clientid: str = ""
    spotify_clientsecret: str = ""

    command_prefix: str = "!"
    commands_via_mention: bool = True
    bound_channels: Set[int] = set()
    unbound_servers: bool = False
    autojoin_channels: Set[int] = set()
    dm_nowplaying: bool = False
    no_nowplaying_auto: bool = False
    nowplaying_channels: Set[int] = set()
    delete_nowplaying: bool = True

    default_volume: float = 0.15
    default_speed: float = 1.0
    skips_required: int = 4
    skip_ratio_required: float = 0.5
    save_videos: bool = True
    storage_retain_autoplay: bool = True
    storage_limit_bytes: int = 0
    storage_limit_days: int = 0
    now_playing_mentions: bool = False
    auto_summon: bool = True
    auto_playlist: bool = True
    auto_playlist_random: bool = True
    auto_playlist_autoskip: bool = False
    auto_playlist_remove_on_block: bool = False
    auto_pause: bool = True
    delete_messages: bool = True
    delete_invoking: bool = False
    delete_delay_short: float = 30.0
    delete_delay_long: float = 60.0
    persistent_queue: bool = True
    status_message: str = ""
    status_include_paused: bool = False
    write_current_song: bool = False
    allow_author_skip: bool = True
    use_opus_probe: bool = False
    use_experimental_equalization: bool = False
    embeds: bool = True
    queue_length: int = 10
    remove_ap: bool = True
    show_config_at_start: bool = False
    legacy_skip: bool = False
    leavenonowners: bool = False
    usealias: bool = True
    searchlist: bool = False
    self_deafen: bool = True
    leave_inactive_channel: bool = False
    leave_inactive_channel_timeout: float = 300.0
    leave_after_queue_empty: bool = False
    leave_player_inactive_for: float = 0.0
    defaultsearchresults: int = 3
    enable_options_per_guild: bool = False
    footer_text: str = DEFAULT_FOOTER_TEXT
    remove_embed_footer: bool = False
    defaultround_robin_queue: bool = False
    enable_network_checker: bool = False
    enable_local_media: bool = False
    enable_queue_history_global: bool = False
    enable_queue_history_guilds: bool = False
    auto_unpause_on_play: bool = False
    ytdlp_proxy: str = ""
    ytdlp_user_agent: str = ""
    ytdlp_oauth2_url: str = ""

    ytdlp_oauth2_client_id: str = (
        "861556708454-d6dlm3lh05idd8npek18k6be8ba3oc68.apps.googleusercontent.com"
    )
    ytdlp_oauth2_client_secret: str = "SboVhoG9s0rNafixCSGGKXAT"

    ytdlp_use_oauth2: bool = False
    pre_download_next_song: bool = True

    song_blocklist: Set[str] = set()
    user_blocklist: Set[int] = set()
    song_blocklist_enabled: bool = False
    # default true here since the file being populated was previously how it was enabled.
    user_blocklist_enabled: bool = True

    logs_max_kept: int = DEFAULT_LOGS_KEPT
    logs_date_format: str = DEFAULT_LOGS_ROTATE_FORMAT

    # Create path objects from the constants.
    options_file: pathlib.Path = write_path(DEFAULT_OPTIONS_FILE)
    user_blocklist_file: pathlib.Path = write_path(DEFAULT_USER_BLOCKLIST_FILE)
    song_blocklist_file: pathlib.Path = write_path(DEFAULT_SONG_BLOCKLIST_FILE)
    auto_playlist_dir: pathlib.Path = write_path(DEFAULT_PLAYLIST_DIR)
    media_file_dir: pathlib.Path = write_path(DEFAULT_MEDIA_FILE_DIR)
    audio_cache_path: pathlib.Path = write_path(DEFAULT_AUDIO_CACHE_DIR)

    @staticmethod
    def _debug_level() -> Tuple[str, int]:
        """default values for debug log level configs"""
        debug_level: int = getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO)
        debug_level_str: str = (
            DEFAULT_LOG_LEVEL
            if logging.getLevelName(debug_level) == DEFAULT_LOG_LEVEL
            else logging.getLevelName(debug_level)
        )
        return (debug_level_str, debug_level)


class ConfigOption:
    """Basic data model for individual registered options."""

    def __init__(
        self,
        section: str,
        option: str,
        dest: str,
        default: RegTypes,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "get",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> None:
        """
        Defines a configuration option in MusicBot and attributes used to
        identify the option both at runtime and in the INI file.

        :param: section:    The section this option belongs to, case sensitive.
        :param: option:     The name of this option, case sensitive.
        :param: dest:       The name of a Config attribute the value of this option will be stored in.
        :param: getter:     The name of a callable in ConfigParser used to get this option value.
        :param: default:    The default value for this option if it is missing or invalid.
        :param: comment:    A comment or help text to show for this option.
        :param: editable:   If this option can be changed via commands.
        :param: invisible:  (Permissions only) hide from display when formatted for per-user display.
        :param: empty_display_val   Value shown when the parsed value is empty or None.
        :param: default_is_empty    Save an empty value to INI file when the option value is default.
        """
        self.section = section
        self.option = option
        self.dest = dest
        self.getter = getter
        self.default = default
        self.comment = comment
        self.comment_args = comment_args
        self.editable = editable
        self.invisible = invisible
        self.empty_display_val = empty_display_val
        self.default_is_empty = default_is_empty

    def __str__(self) -> str:
        return f"[{self.section}] > {self.option}"


class ConfigOptionRegistry:
    """
    Management system for registering config options which provides methods to
    query the state of configurations or translate them.
    """

    def __init__(
        self, config: Union[Config, "Permissions"], parser: "ExtendedConfigParser"
    ) -> None:
        """
        Manage a configuration registry that associates config options to their
        parent section, a runtime name, validation for values, and commentary
        or other help text about the option.
        """
        self._config = config
        self._parser = parser

        # registered options.
        self._option_list: List[ConfigOption] = []

        # registered sections.
        self._sections: Set[str] = set()
        self._options: Set[str] = set()
        self._distinct_options: Set[str] = set()
        self._has_resolver: bool = True

        # set up missing config data.
        self.ini_missing_options: Set[ConfigOption] = set()
        self.ini_missing_sections: Set[str] = set()

    @property
    def sections(self) -> Set[str]:
        """Available section names."""
        return self._sections

    @property
    def option_keys(self) -> Set[str]:
        """Available options with section names."""
        return self._options

    @property
    def option_list(self) -> List[ConfigOption]:
        """Non-settable option list."""
        return self._option_list

    @property
    def resolver_available(self) -> bool:
        """Status of option name-to-section resolver. If False, resolving cannot be used."""
        return self._has_resolver

    def update_missing_config(self) -> None:
        """
        Checks over the ini file for options missing from the file.
        It only considers registered options, rather than looking at examples file.
        As such it should be run after all options are registered.
        """
        # load the unique sections and options from the parser.
        p_section_set = set()
        p_key_set = set()
        parser_sections = dict(self._parser.items())
        for section in parser_sections:
            p_section_set.add(section)
            opts = set(parser_sections[section].keys())
            for opt in opts:
                p_key_set.add(f"[{section}] > {opt}")

        # update the missing sections registry.
        self.ini_missing_sections = self._sections - p_section_set

        # populate the missing options registry.
        for option in self._option_list:
            if str(option) not in p_key_set:
                self.ini_missing_options.add(option)

    def get_sections_from_option(self, option_name: str) -> Set[str]:
        """
        Get the Section name(s) associated with the given `option_name` if available.

        :return:  A set containing one or more section names, or an empty set if no option exists.
        """
        if self._has_resolver:
            return set(o.section for o in self._option_list if o.option == option_name)
        return set()

    def get_updated_options(self) -> List[ConfigOption]:
        """
        Get ConfigOptions that have been updated at runtime.
        """
        changed = []
        for option in self._option_list:
            if not hasattr(self._config, option.dest):
                raise AttributeError(
                    f"Dev Bug! Attribute `Config.{option.dest}` does not exist."
                )

            if not hasattr(self._parser, option.getter):
                raise AttributeError(
                    f"Dev Bug! Method `*ConfigParser.{option.getter}` does not exist."
                )

            p_getter = getattr(self._parser, option.getter)
            config_value = getattr(self._config, option.dest)
            parser_value = p_getter(
                option.section, option.option, fallback=option.default
            )

            # We only care about changed options that are editable.
            if config_value != parser_value and option.editable:
                changed.append(option)
        return changed

    def get_config_option(self, section: str, option: str) -> Optional[ConfigOption]:
        """
        Gets the config option if it exists, or returns None
        """
        for opt in self._option_list:
            if opt.section == section and opt.option == option:
                return opt
        return None

    def get_values(self, opt: ConfigOption) -> Tuple[RegTypes, str, str]:
        """
        Get the values in Config and *ConfigParser for this config option.
        Returned tuple contains parsed value, ini-string, and a display string
        for the parsed config value if applicable.
        Display string may be empty if not used.
        """
        if not opt.editable:
            return ("", "", "")

        if not hasattr(self._config, opt.dest):
            raise AttributeError(
                f"Dev Bug! Attribute `Config.{opt.dest}` does not exist."
            )

        if not hasattr(self._parser, opt.getter):
            raise AttributeError(
                f"Dev Bug! Method `*ConfigParser.{opt.getter}` does not exist."
            )

        p_getter = getattr(self._parser, opt.getter)
        config_value = getattr(self._config, opt.dest)
        parser_value = p_getter(opt.section, opt.option, fallback=opt.default)

        display_config_value = ""
        if opt.empty_display_val:
            display_config_value = opt.empty_display_val

        return (config_value, parser_value, display_config_value)

    def validate_register_destinations(self) -> None:
        """Check all configured options for matching destination definitions."""
        errors = []
        for opt in self._option_list:
            if not hasattr(self._config, opt.dest):
                errors.append(
                    f"Config Option `{opt}` has an missing destination named:  {opt.dest}"
                )
        if errors:
            msg = "Dev Bug!  Some options failed config validation.\n"
            msg += "\n".join(errors)
            raise RuntimeError(msg)

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: str,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "get",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = " ",
        default_is_empty: bool = False,
    ) -> str:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: bool,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getboolean",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> bool:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: int,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getint",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> int:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: float,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getfloat",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> float:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: Set[int],
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getidset",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = " ",
        default_is_empty: bool = False,
    ) -> Set[int]:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: Set[str],
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getstrset",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = " ",
        default_is_empty: bool = False,
    ) -> Set[str]:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: DebugLevel,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getdebuglevel",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> DebugLevel:
        pass

    @overload
    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: pathlib.Path,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "getpathlike",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> pathlib.Path:
        pass

    def init_option(
        self,
        section: str,
        option: str,
        dest: str,
        default: RegTypes,
        comment: str,
        comment_args: CommentArgs = None,
        getter: str = "get",
        editable: bool = True,
        invisible: bool = False,
        empty_display_val: str = "",
        default_is_empty: bool = False,
    ) -> RegTypes:
        """
        Register an option while getting its configuration value at the same time.

        :param: section:    The section this option belongs to, case sensitive.
        :param: option:     The name of this option, case sensitive.
        :param: dest:       The name of a Config attribute the value of this option will be stored in.
        :param: getter:     The name of a callable in ConfigParser used to get this option value.
        :param: default:    The default value for this option if it is missing or invalid.
        :param: comment:    A comment or help text to show for this option.
        :param: editable:   If this option can be changed via commands.
        """
        # Check that the getter function exists and is callable.
        if not hasattr(self._parser, getter):
            raise ValueError(
                f"Dev Bug! There is no *ConfigParser function by the name of: {getter}"
            )
        if not callable(getattr(self._parser, getter)):
            raise TypeError(
                f"Dev Bug! The *ConfigParser.{getter} attribute is not a callable function."
            )

        # add the option to the registry.
        config_opt = ConfigOption(
            section=section,
            option=option,
            dest=dest,
            default=default,
            getter=getter,
            comment=comment,
            comment_args=comment_args,
            editable=editable,
            invisible=invisible,
            empty_display_val=empty_display_val,
            default_is_empty=default_is_empty,
        )
        self._option_list.append(config_opt)
        self._sections.add(section)
        if str(config_opt) in self._options:
            log.warning(
                "Option names are not unique between INI sections!  Resolver is disabled."
            )
            self._has_resolver = False
        self._options.add(str(config_opt))
        self._distinct_options.add(option)

        # get the current config value.
        getfunc = getattr(self._parser, getter)
        opt: RegTypes = getfunc(section, option, fallback=default)

        # sanity check that default actually matches the type from getter.
        if not isinstance(opt, type(default)):
            raise TypeError(
                "Dev Bug! Are you using the wrong getter for this option?\n"
                f"[{section}] > {option} has type: {type(default)} but got type: {type(opt)}"
            )
        return opt

    def to_ini(self, option: ConfigOption, use_default: bool = False) -> str:
        """
        Convert the parsed config value into an INI value.
        This method does not perform validation, simply converts the value.

        :param: use_default:  return the default value instead of current config.
        """
        if not hasattr(self._config, option.dest):
            raise AttributeError(
                f"Dev Bug! Attribute `Config.{option.dest}` does not exist."
            )

        if use_default:
            conf_value = option.default
        else:
            conf_value = getattr(self._config, option.dest)
        return self._value_to_ini(conf_value, option.getter)

    def _value_to_ini(self, conf_value: RegTypes, getter: str) -> str:
        """Converts a value to an ini string."""
        if getter == "get":
            return str(conf_value)

        if getter == "getint":
            return str(conf_value)

        if getter == "getfloat":
            return f"{conf_value:.3f}"

        if getter == "getboolean":
            return "yes" if conf_value else "no"

        if getter in ["getstrset", "getidset"] and isinstance(conf_value, set):
            return ", ".join(str(x) for x in conf_value)

        if getter == "getdatasize" and isinstance(conf_value, int):
            if conf_value:
                return format_size_from_bytes(conf_value)
            return str(conf_value)

        if getter == "getduration" and isinstance(conf_value, (int, float)):
            td = datetime.timedelta(seconds=round(conf_value))
            return str(td)

        if getter == "getpathlike":
            return str(conf_value)

        # NOTE: debug_level is not editable, but can be displayed.
        if (
            getter == "getdebuglevel"
            and isinstance(conf_value, tuple)
            and isinstance(conf_value[0], str)
            and isinstance(conf_value[1], int)
        ):
            return str(logging.getLevelName(conf_value[1]))

        return str(conf_value)

    def export_markdown(self) -> str:
        """
        Transform registered config / permissions options into "markdown".
        This is intended to generate documentation from the code for publishing to pages.
        Currently will print options in order they are registered.
        But prints sections in the order ConfigParser loads them.
        """
        basedir = get_write_base()
        if not basedir:
            basedir = os.getcwd()
        md_sections = {}
        for opt in self.option_list:
            dval = self.to_ini(opt, use_default=True)
            if opt.getter == "getpathlike":
                dval = dval.replace(basedir, ".")
            if dval.strip() == "":
                if opt.empty_display_val:
                    dval = f"<code>{opt.empty_display_val}</code>"
                else:
                    dval = "<i>*empty*</i>"
            else:
                dval = f"<code>{dval}</code>"

            # TODO: default values need to be consistent i18n will probably change this.
            # fmt: off
            if opt.comment_args:
                comment = opt.comment % opt.comment_args
            else:
                comment = opt.comment
            comment = comment.replace("\n", "<br>\n")
            md_option = (
                f"<details>\n  <summary>{opt.option}</summary>\n\n"
                f"{comment}<br>  \n"
                f"<strong>Default Value:</strong> {dval}  \n</details>  \n"
            )
            # fmt: on
            if opt.section not in md_sections:
                md_sections[opt.section] = [md_option]
            else:
                md_sections[opt.section].append(md_option)

        markdown = ""
        for sect in self._parser.sections():
            opts = md_sections[sect]
            markdown += f"#### [{sect}]\n\n{''.join(opts)}\n\n"

        return markdown

    def write_default_ini(self, filename: pathlib.Path) -> bool:
        """Uses config registry to generate an example_options.ini file."""
        try:
            cu = configupdater.ConfigUpdater()
            cu.optionxform = str  # type: ignore

            # TODO: shift this to a constant maybe...
            # I hate hard-coding this, but it maintains the order of sections we want.
            for section in ["Credentials", "Permissions", "Chat", "MusicBot", "Files"]:
                cu.add_section(section)

            # add comments to head of file.
            adder = cu["Credentials"].add_before
            head_comment = (
                "This is the configuration file for MusicBot. Do not edit this file using Notepad.\n"
                "Use Notepad++ or a code editor like Visual Studio Code.\n"
                "For help, see: https://just-some-bots.github.io/MusicBot/ \n"
                "\n"
                "This file was generated by MusicBot, it contains all options set to their default values."
            )
            for line in head_comment.split("\n"):
                adder.comment(line)
            adder.space()

            for opt in self.option_list:
                if opt.default_is_empty:
                    ini_val = ""
                else:
                    ini_val = self.to_ini(opt, use_default=True)
                cu[opt.section][opt.option] = ini_val
                adder = cu[opt.section][opt.option].add_before
                if opt.comment_args:
                    comment = opt.comment % opt.comment_args
                else:
                    comment = opt.comment
                c_lines = comment.split("\n")
                if len(c_lines) > 1:
                    for line in c_lines:
                        adder.comment(line)
                else:
                    adder.comment(opt.comment)
                cu[opt.section][opt.option].add_after.space()

            with open(filename, "w", encoding="utf8") as fp:
                cu.write(fp)

            return True
        except (
            OSError,
            AttributeError,
            configparser.DuplicateSectionError,
            configparser.ParsingError,
        ):
            log.exception("Failed to save default INI file at:  %s", filename)
            return False


class ExtendedConfigParser(configparser.ConfigParser):
    """
    A collection of typed converters to extend ConfigParser.
    These methods are also responsible for validation and raising HelpfulErrors
    for issues detected with the values.
    """

    def __init__(self) -> None:
        # If empty_lines_in_values is ever true, config editing needs refactor.
        # Probably should use ConfigUpdater package instead.
        super().__init__(interpolation=None, empty_lines_in_values=False)
        self.error_preface = "Error loading config value:"

    def optionxform(self, optionstr: str) -> str:
        """
        This is an override for ConfigParser key parsing.
        by default ConfigParser uses str.lower() we just return to keep the case.
        """
        return optionstr

    def fetch_all_keys(self) -> List[str]:
        """
        Gather all config keys for all sections of this config into a list.
        This -will- return duplicate keys if they happen to exist in config.
        """
        sects = dict(self.items())
        keys = []
        for k in sects:
            s = sects[k]
            keys += list(s.keys())
        return keys

    def getstr(
        self,
        section: str,
        key: str,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
        fallback: str = "",
    ) -> str:
        """A version of get which strips spaces and uses fallback / default for empty values."""
        val = self.get(section, key, fallback=fallback, raw=raw, vars=vars).strip()
        if not val:
            return fallback
        return val

    def getboolean(  # type: ignore[override]
        self,
        section: str,
        option: str,
        *,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
        fallback: bool = False,
        **kwargs: Optional[Mapping[str, Any]],
    ) -> bool:
        """Make getboolean less bitchy about empty values, so it uses fallback instead."""
        val = self.get(section, option, fallback="", raw=raw, vars=vars).strip()
        if not val:
            return fallback

        try:
            return super().getboolean(section, option, fallback=fallback)
        except ValueError:
            return fallback

    def getownerid(
        self,
        section: str,
        key: str,
        fallback: int = 0,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> int:
        """get the owner ID or 0 for auto"""
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val:
            return fallback
        if val.lower() == "auto":
            return 0

        try:
            return int(val)
        except ValueError as e:
            raise HelpfulError(
                # fmt: off
                "Error loading config value.\n"
                "\n"
                "Problem:\n"
                "  The owner ID in [%(section)s] > %(option)s is not valid.\n"
                "\n"
                "Solution:\n"
                "  Set %(option)s to a numerical ID or set it to `auto` or `0` for automatic owner binding.",
                # fmt: on
                fmt_args={"section": section, "option": key},
            ) from e

    def getpathlike(
        self,
        section: str,
        key: str,
        fallback: pathlib.Path,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> pathlib.Path:
        """
        get a config value and parse it as a Path object.
        the `fallback` argument is required.
        """
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val and fallback:
            return fallback
        if not val and not fallback:
            raise ValueError(
                f"The option [{section}] > {key} does not have a valid fallback value. This is a bug!"
            )

        try:
            return pathlib.Path(val).resolve(strict=False)
        except RuntimeError as e:
            raise HelpfulError(
                # fmt: off
                "Error loading config value.\n"
                "\n"
                "Problem:\n"
                "  The config option [%(section)s] > %(option)s is not a valid file location.\n"
                "\n"
                "Solution:\n"
                "  Check the path setting and make sure the file exists and is accessible to MusicBot.",
                # fmt: on
                fmt_args={"section": section, "option": key},
            ) from e

    def getidset(
        self,
        section: str,
        key: str,
        fallback: Optional[Set[int]] = None,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> Set[int]:
        """get a config value and parse it as a set of ID values."""
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val and fallback:
            return set(fallback)

        str_ids = val.replace(",", " ").split()
        try:
            return set(int(i) for i in str_ids)
        except ValueError as e:
            raise HelpfulError(
                # fmt: off
                "Error loading config value.\n"
                "\n"
                "Problem:\n"
                "  One of the IDs in option [%(section)s] > %(option)s is invalid.\n"
                "\n"
                "Solution:\n"
                "  Ensure all IDs are numerical, and separated only by spaces or commas.",
                # fmt: on
                fmt_args={"section": section, "option": key},
            ) from e

    def getdebuglevel(
        self,
        section: str,
        key: str,
        fallback: str = "",
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> DebugLevel:
        """get a config value an parse it as a logger level."""
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip().upper()
        if not val and fallback:
            if isinstance(fallback, tuple):
                val = fallback[0]
            else:
                val = fallback

        int_level = 0
        str_level = val
        if hasattr(logging, val):
            int_level = getattr(logging, val)
            return (str_level, int_level)

        int_level = getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO)
        str_level = logging.getLevelName(int_level)
        log.warning(
            'Invalid DebugLevel option "%(value)s" given, falling back to level: %(fallback)s',
            {"value": val, "fallback": str_level},
        )
        return (str_level, int_level)

    def getdatasize(
        self,
        section: str,
        key: str,
        fallback: int = 0,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> int:
        """get a config value and parse it as a human readable data size"""
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val and fallback:
            return fallback
        try:
            return format_size_to_bytes(val)
        except ValueError:
            log.warning(
                "Option [%(section)s] > %(option)s has invalid config value '%(value)s' using default instead.",
                {"section": section, "option": key, "value": val},
            )
            return fallback

    def getpercent(
        self,
        section: str,
        key: str,
        fallback: float = 0.0,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> float:
        """
        Get a config value and parse it as a percentage.
        Always returns a positive value between 0 and 1 inclusive.
        """
        if fallback:
            fallback = max(0.0, min(abs(fallback), 1.0))

        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val and fallback:
            return fallback

        v = 0.0
        # account for literal percentage character: %
        if val.startswith("%") or val.endswith("%"):
            try:
                ival = val.replace("%", "").strip()
                v = abs(int(ival)) / 100
            except (ValueError, TypeError):
                if fallback:
                    return fallback
                raise

        # account for explicit float and implied percentage.
        else:
            try:
                v = abs(float(val))
                # if greater than 1, assume implied percentage.
                if v > 1:
                    v = v / 100
            except (ValueError, TypeError):
                if fallback:
                    return fallback
                raise

        if v > 1:
            log.warning(
                "Option [%(section)s] > %(option)s has a value greater than 100 %% (%(value)s) and will be set to %(fallback)s instead.",
                {
                    "section": section,
                    "option": key,
                    "value": val,
                    "fallback": fallback if fallback else 1,
                },
            )
            v = fallback if fallback else 1

        return v

    def getduration(
        self,
        section: str,
        key: str,
        fallback: Union[int, float] = 0,
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> float:
        """get a config value parsed as a time duration."""
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val and fallback:
            return float(fallback)
        seconds = format_time_to_seconds(val)
        return float(seconds)

    def getstrset(
        self,
        section: str,
        key: str,
        fallback: Set[str],
        raw: bool = False,
        vars: ConfVars = None,  # pylint: disable=redefined-builtin
    ) -> Set[str]:
        """get a config value parsed as a set of string values."""
        val = self.get(section, key, fallback="", raw=raw, vars=vars).strip()
        if not val and fallback:
            return set(fallback)
        return set(x for x in val.replace(",", " ").split())


class ConfigRenameManager:
    """
    This class provides a method to move or rename config options.
    All renaming is done sequentially, to ensure that older versions of config
    can be carried into newer versions with minimal manual edits.
    """

    def __init__(self, config_file: pathlib.Path) -> None:
        """Register all config remaps, past or present."""
        self._cfg_file = config_file

        # The format of config remap items is as follows:
        # (origin_section, origin_name, new_section, new_name)
        # These values are case sensitive, and must match existing options.
        # If not found, no error/warning is raised, it is assumed they are renamed already.
        self._remap: List[Tuple[str, str, str, str]] = [
            # fmt: off
            # Rename LeaveAfterSong and Blacklist options  @  2024/02/21
            ("MusicBot", "LeaveAfterSong", "MusicBot", "LeaveAfterQueueEmpty"),

            # Move chat-related to Chat section  @  2024/04/02
            # Also renames UseAlias to UseCommandAlias for clarity.
            ("MusicBot", "DeleteMessages",       "Chat", "DeleteMessages"),  # noqa: E241
            ("MusicBot", "DeleteInvoking",       "Chat", "DeleteInvoking"),  # noqa: E241
            ("MusicBot", "NowPlayingMentions",   "Chat", "NowPlayingMentions"),  # noqa: E241
            ("MusicBot", "UseEmbeds",            "Chat", "UseEmbeds"),  # noqa: E241
            ("MusicBot", "UseAlias",             "Chat", "UseCommandAlias"),  # noqa: E241
            ("MusicBot", "CustomEmbedFooter",    "Chat", "CustomEmbedFooter"),  # noqa: E241
            ("MusicBot", "EnablePrefixPerGuild", "Chat", "EnablePrefixPerGuild"),
            ("MusicBot", "SearchList",           "Chat", "SearchList"),  # noqa: E241
            ("MusicBot", "DefaultSearchResults", "Chat", "DefaultSearchResults"),
            # fmt: on
        ]
        self.update_config_options()

    def _handle_remap_item(
        self, cu: configupdater.ConfigUpdater, remap: Tuple[str, str, str, str]
    ) -> None:
        """Logic for updating one item from the remap."""
        o_sect, o_opt, n_sect, n_opt = remap

        log.debug(
            "Renaming INI file entry [%(old_s)s] > %(old_o)s  to  [%(new_s)s] > %(new_o)s",
            {"old_s": o_sect, "old_o": o_opt, "new_s": n_sect, "new_o": n_opt},
        )

        opt = cu.get(o_sect, o_opt)
        # Simply rename the config in-place if possible.
        if o_sect == n_sect:
            cu[n_sect].insert_at(opt.container_idx).option(
                n_opt,
                opt.value,
            )
            cu.remove_option(o_sect, o_opt)

        # Move the option and comments.
        else:
            opt = cu.get(o_sect, o_opt)
            blocks = []
            prev_block = opt.previous_block
            while prev_block is not None:
                if not isinstance(prev_block, (Comment, Space)):
                    break
                # prime the next block to inspect.
                np_block = prev_block.previous_block
                # detach this block for reuse.
                block = prev_block.detach()
                blocks.append(block)
                # move on to the next block.
                prev_block = np_block

            # Remove the old option, add new with the same value.
            cu.remove_option(o_sect, o_opt)
            cu[n_sect][n_opt] = opt.value
            # Add the comments to the new option.
            blocks.reverse()
            for block in blocks:
                if isinstance(block, Comment):
                    cu[n_sect][n_opt].add_before.comment(str(block))
                if isinstance(block, Space):
                    cu[n_sect][n_opt].add_before.space(len(block.lines))

    def update_config_options(self) -> None:
        """
        Uses ConfigUpdater to find mapped options and rename them.
        """
        try:
            cu = configupdater.ConfigUpdater()
            cu.optionxform = str  # type: ignore
            cu.read(self._cfg_file, encoding="utf8")

            updates = 0
            for item in self._remap:
                if cu.has_option(item[0], item[1]):
                    updates += 1
                    self._handle_remap_item(cu, item)

            if updates:
                log.debug("Upgrading config file with renamed options...")
                # Ensure some spacing exists at the end of sections.
                for sect in cu.iter_sections():
                    if not isinstance(sect.last_block, Space):
                        sect.add_after.space(2)

                # write the changes to file.
                cu.update_file()

        except (
            OSError,
            AttributeError,
            configparser.DuplicateOptionError,
            configparser.DuplicateSectionError,
            configparser.ParsingError,
        ):
            log.exception(
                "Failed to upgrade config.  You'll need to upgrade it manually."
            )


class Blocklist:
    """
    Base class for more specific block lists.
    """

    def __init__(self, blocklist_file: pathlib.Path, comment_char: str = "#") -> None:
        """
        Loads a block list into memory, ignoring empty lines and commented lines,
        as well as striping comments from string remainders.

        Note: If the default comment character `#` is used, this function will
        strip away discriminators from usernames.
        User IDs should be used instead, if definite ID is needed.

        Similarly, URL fragments will be removed from URLs as well. This typically
        is not an issue as fragments are only client-side by specification.

        :param: blocklist_file:  A file path to a block list, which will be created if it does not exist.
        :param: comment_char:  A character used to denote comments in the file.
        """
        self._blocklist_file: pathlib.Path = blocklist_file
        self._comment_char = comment_char
        self.items: Set[str] = set()

        self.load_blocklist_file()

    def __len__(self) -> int:
        """Gets the number of items in the block list."""
        return len(self.items)

    def load_blocklist_file(self) -> bool:
        """
        Loads (or reloads) the block list file into memory.

        :returns:  True if loading finished False if it could not for any reason.
        """
        if not self._blocklist_file.is_file():
            log.warning("Block list file not found:  %s", self._blocklist_file)
            return False

        try:
            with open(self._blocklist_file, "r", encoding="utf8") as f:
                for line in f:
                    line = line.strip()

                    if line:
                        # Skip lines starting with comments.
                        if self._comment_char and line.startswith(self._comment_char):
                            continue

                        # strip comments from the remainder of a line.
                        if self._comment_char and self._comment_char in line:
                            line = line.split(self._comment_char, maxsplit=1)[0].strip()

                        self.items.add(line)
            return True
        except OSError:
            log.error(
                "Could not load block list from file:  %s",
                self._blocklist_file,
                exc_info=True,
            )

        return False

    def append_items(
        self,
        items: Iterable[str],
        comment: str = "",
        spacer: str = "\t\t%s ",
    ) -> bool:
        """
        Appends the given `items` to the block list file.

        :param: items:  An iterable of strings to be appended.
        :param: comment:  An optional comment added to each new item.
        :param: spacer:
            A format string for placing comments, where %s is replaced with the
            comment character used by this block list.

        :returns: True if updating is successful.
        """
        if not self._blocklist_file.is_file():
            return False

        try:
            space = ""
            if comment:
                space = spacer.format(self._comment_char)
            with open(self._blocklist_file, "a", encoding="utf8") as f:
                for item in items:
                    f.write(f"{item}{space}{comment}\n")
                    self.items.add(item)
            return True
        except OSError:
            log.error(
                "Could not update the block list file:  %s",
                self._blocklist_file,
                exc_info=True,
            )
        return False

    def remove_items(self, items: Iterable[str]) -> bool:
        """
        Find and remove the given `items` from the block list file.

        :returns: True if updating is successful.
        """
        if not self._blocklist_file.is_file():
            return False

        self.items.difference_update(set(items))

        try:
            # read the original file in and remove lines with our items.
            # this is done to preserve the comments and formatting.
            lines = self._blocklist_file.read_text(encoding="utf8").split("\n")
            with open(self._blocklist_file, "w", encoding="utf8") as f:
                for line in lines:
                    # strip comment from line.
                    line_strip = line.split(self._comment_char, maxsplit=1)[0].strip()

                    # don't add the line if it matches any given items.
                    if line in items or line_strip in items:
                        continue
                    f.write(f"{line}\n")

        except OSError:
            log.error(
                "Could not update the block list file:  %s",
                self._blocklist_file,
                exc_info=True,
            )
        return False


class UserBlocklist(Blocklist):
    def __init__(self, blocklist_file: pathlib.Path, comment_char: str = "#") -> None:
        """
        A UserBlocklist manages a block list which contains discord usernames and IDs.
        """
        self._handle_legacy_file(blocklist_file)

        c = comment_char
        create_file_ifnoexist(
            blocklist_file,
            [
                f"{c} MusicBot discord user block list denies all access to bot.\n",
                f"{c} Add one User ID or username per each line.\n",
                f"{c} Nick-names or server-profile names are not checked.\n",
                f"{c} User ID is prefered. Usernames with discriminators (ex: User#1234) may not work.\n",
                f"{c} In this file '{c}' is a comment character. All characters following it are ignored.\n",
            ],
        )
        super().__init__(blocklist_file, comment_char)
        log.debug(
            "Loaded User Block list with %s entries.",
            len(self.items),
        )

    def _handle_legacy_file(self, new_file: pathlib.Path) -> None:
        """
        In case the original, ambiguous block list file exists, lets rename it.
        """
        old_file = write_path(DEPRECATED_USER_BLACKLIST)
        if old_file.is_file() and not new_file.is_file():
            log.warning(
                "We found a legacy blacklist file, it will be renamed to:  %s",
                new_file,
            )
            old_file.rename(new_file)

    def is_blocked(self, user: Union["discord.User", "discord.Member"]) -> bool:
        """
        Checks if the given `user` has their discord username or ID listed in the loaded block list.
        """
        user_id = str(user.id)
        # this should only consider discord username, not nick/ server profile.
        user_name = user.name
        if user_id in self.items or user_name in self.items:
            return True
        return False

    def is_disjoint(
        self, users: Iterable[Union["discord.User", "discord.Member"]]
    ) -> bool:
        """
        Returns False if any of the `users` are listed in the block list.

        :param: users:  A list or set of discord Users or Members.
        """
        return not any(self.is_blocked(u) for u in users)


class SongBlocklist(Blocklist):
    def __init__(self, blocklist_file: pathlib.Path, comment_char: str = "#") -> None:
        """
        A SongBlocklist manages a block list which contains song URLs or other
        words and phrases that should be blocked from playback.
        """
        c = comment_char
        create_file_ifnoexist(
            blocklist_file,
            [
                f"{c} MusicBot discord song block list denies songs by URL or Title.\n",
                f"{c} Add one URL or Title per line. Leading and trailing space is ignored.\n",
                f"{c} This list is matched loosely, with case sensitivity, so adding 'press'\n",
                f"{c} will block 'juice press' and 'press release' but not 'Press'\n",
                f"{c} Block list entries will be tested against input and extraction info.\n",
                f"{c} Lines starting with {c} are comments. All characters follow it are ignored.\n",
            ],
        )
        super().__init__(blocklist_file, comment_char)
        log.debug("Loaded a Song Block list with %s entries.", len(self.items))

    def is_blocked(self, song_subject: str) -> bool:
        """
        Checks if the given `song_subject` contains any entry in the song block list.

        :param: song_subject:  Any input the bot player commands will take or pass to ytdl extraction.
        """
        return any(x in song_subject for x in self.items)
import subprocess
from typing import List

# VERSION is determined by asking the `git` executable about the current repository.
# This fails if not cloned, or if git is not available for some reason.
# VERSION should never be empty though.
# Note this code is duplicated in update.py for stand-alone use.
VERSION: str = ""
try:
    # Get the last release tag, number of commits since, and g{commit_id} as string.
    _VERSION_P1 = (
        subprocess.check_output(["git", "describe", "--tags", "--always"])
        .decode("ascii")
        .strip()
    )
    # Check if any tracked files are modified for -modded version flag.
    _VERSION_P2 = (
        subprocess.check_output(
            ["git", "-c", "core.fileMode=false", "status", "-suno", "--porcelain"]
        )
        .decode("ascii")
        .strip()
    )
    if _VERSION_P2:
        _VERSION_P2 = "-modded"
    else:
        _VERSION_P2 = ""

    VERSION = f"{_VERSION_P1}{_VERSION_P2}"

except (subprocess.SubprocessError, OSError, ValueError) as e:
    print(f"Failed setting version constant, reason:  {str(e)}")
    VERSION = "version_unknown"

# constant string exempt from i18n
DEFAULT_FOOTER_TEXT: str = f"Just-Some-Bots/MusicBot ({VERSION})"
DEFAULT_BOT_NAME: str = "MusicBot"
DEFAULT_BOT_ICON: str = "https://i.imgur.com/gFHBoZA.png"
DEFAULT_OWNER_GROUP_NAME: str = "Owner (auto)"
DEFAULT_PERMS_GROUP_NAME: str = "Default"
# This UA string is used by MusicBot only for the aiohttp session.
# Meaning discord API and spotify API communications.
# NOT used by ytdlp, they have a dynamic UA selection feature.
MUSICBOT_USER_AGENT_AIOHTTP: str = f"MusicBot/{VERSION}"
MUSICBOT_GIT_URL: str = "https://github.com/Just-Some-Bots/MusicBot/"
# The Environment variable MusicBot checks for if no Token is given in the config file.
MUSICBOT_TOKEN_ENV_VAR: str = "MUSICBOT_TOKEN"

# File path constants
DEFAULT_OPTIONS_FILE: str = "config/options.ini"
DEFAULT_PERMS_FILE: str = "config/permissions.ini"
DEFAULT_I18N_DIR: str = "i18n/"
DEFAULT_I18N_LANG: str = "en_US"
DEFAULT_COMMAND_ALIAS_FILE: str = "config/aliases.json"
DEFAULT_USER_BLOCKLIST_FILE: str = "config/blocklist_users.txt"
DEFAULT_SONG_BLOCKLIST_FILE: str = "config/blocklist_songs.txt"
DEPRECATED_USER_BLACKLIST: str = "config/blacklist.txt"
OLD_DEFAULT_AUTOPLAYLIST_FILE: str = "config/autoplaylist.txt"
OLD_BUNDLED_AUTOPLAYLIST_FILE: str = "config/_autoplaylist.txt"
DEFAULT_PLAYLIST_DIR: str = "config/playlists/"
DEFAULT_MEDIA_FILE_DIR: str = "media/"
DEFAULT_AUDIO_CACHE_DIR: str = "audio_cache/"
DEFAULT_DATA_DIR: str = "data/"

# File names within the DEFAULT_DATA_DIR or guild folders.
DATA_FILE_SERVERS: str = "server_names.txt"
DATA_FILE_CACHEMAP: str = "playlist_cachemap.json"
DATA_FILE_COOKIES: str = "cookies.txt"  # No support for this, go read yt-dlp docs.
DATA_FILE_YTDLP_OAUTH2: str = "oauth2.token"
DATA_GUILD_FILE_QUEUE: str = "queue.json"
DATA_GUILD_FILE_CUR_SONG: str = "current.txt"
DATA_GUILD_FILE_OPTIONS: str = "options.json"

I18N_DISCORD_TEXT_DOMAIN: str = "musicbot_messages"
I18N_LOGFILE_TEXT_DOMAIN: str = "musicbot_logs"

# Example config files.
EXAMPLE_OPTIONS_FILE: str = "config/example_options.ini"
EXAMPLE_PERMS_FILE: str = "config/example_permissions.ini"
EXAMPLE_COMMAND_ALIAS_FILE: str = "config/example_aliases.json"

# Playlist related settings.
APL_FILE_DEFAULT: str = "default.txt"
APL_FILE_HISTORY: str = "history.txt"
APL_FILE_APLCOPY: str = "autoplaylist.txt"

# Logging related constants
DEFAULT_MUSICBOT_LOG_FILE: str = "logs/musicbot.log"
DEFAULT_DISCORD_LOG_FILE: str = "logs/discord.log"
# Default is 0, for no rotation at all.
DEFAULT_LOGS_KEPT: int = 0
MAXIMUM_LOGS_LIMIT: int = 100
# This value is run through strftime() and then sandwiched between
DEFAULT_LOGS_ROTATE_FORMAT: str = ".ended-%Y-%j-%H%m%S"
# Default log level can be one of:
# CRITICAL, ERROR, WARNING, INFO, DEBUG,
# VOICEDEBUG, FFMPEG, NOISY, or EVERYTHING
DEFAULT_LOG_LEVEL: str = "INFO"

# Default target FQDN or IP to ping with network tester.
DEFAULT_PING_TARGET: str = "discord.com"
# Default file location URI used by fallback HTTP network testing.
# This URI must be available via standard HTTP on the above domain/IP target.
DEFAULT_PING_HTTP_URI: str = "/robots.txt"
# Max time in seconds that ping should wait for response.
DEFAULT_PING_TIMEOUT: int = 5
# Time in seconds to wait between pings.
DEFAULT_PING_SLEEP: float = 2
# Ping time settings for HTTP fallback.
FALLBACK_PING_TIMEOUT: int = 15
FALLBACK_PING_SLEEP: float = 4

# Minimum number of seconds to wait for a VoiceClient to connect.
VOICE_CLIENT_RECONNECT_TIMEOUT: int = 5
# Maximum number of retry attempts to make for VoiceClient connection.
# Each retry increases the timeout by multiplying attempts by the above timeout.
VOICE_CLIENT_MAX_RETRY_CONNECT: int = 5

# Maximum number of threads MusicBot will use for downloading and extracting info.
DEFAULT_MAX_INFO_DL_THREADS: int = 2
# Maximum number of seconds to wait for HEAD request on media files.
DEFAULT_MAX_INFO_REQUEST_TIMEOUT: int = 10

# Time to wait before starting pre-download when a new song is playing.
DEFAULT_PRE_DOWNLOAD_DELAY: float = 4.0

# Time in seconds to wait before oauth2 authorization fails.
# This provides time to authorize as well as prevent process hang at shutdown.
DEFAULT_YTDLP_OAUTH2_TTL: float = 180.0

# Default / fallback scopes used for OAuth2 ytdlp plugin.
DEFAULT_YTDLP_OAUTH2_SCOPES: str = (
    "http://gdata.youtube.com https://www.googleapis.com/auth/youtube"
)
# Info Extractors to exclude from OAuth2 patching, when OAuth2 is enabled.
YTDLP_OAUTH2_EXCLUDED_IES: List[str] = [
    "YoutubeBaseInfoExtractor",
    "YoutubeTabBaseInfoExtractor",
]
# Yt-dlp client creators that are not compatible with OAuth2 plugin.
YTDLP_OAUTH2_UNSUPPORTED_CLIENTS: List[str] = [
    "web_creator",
    "android_creator",
    "ios_creator",
]
# Additional Yt-dlp clients to add to the OAuth2 client list.
YTDLP_OAUTH2_CLIENTS: List[str] = ["mweb"]

# Discord and other API constants
DISCORD_MSG_CHAR_LIMIT: int = 2000

# Embed specifics
MUSICBOT_EMBED_COLOR_NORMAL: str = "#7289DA"
MUSICBOT_EMBED_COLOR_ERROR: str = "#CC0000"


EMOJI_CHECK_MARK_BUTTON: str = "\u2705"
EMOJI_CROSS_MARK_BUTTON: str = "\u274E"
EMOJI_STOP_SIGN: str = "\U0001F6D1"
EMOJI_IDLE_ICON: str = "\U0001f634"  # same as \N{SLEEPING FACE}
EMOJI_PLAY_ICON: str = "\u25B6"  # add \uFE0F to make button
EMOJI_PAUSE_ICON: str = "\u23F8\uFE0F"  # add \uFE0F to make button
EMOJI_LAST_ICON: str = "\u23ED\uFE0F"  # next track button
EMOJI_FIRST_ICON: str = "\u23EE\uFE0F"  # last track button
EMOJI_NEXT_ICON: str = "\u23E9"  # fast-forward button
EMOJI_PREV_ICON: str = "\u23EA"  # rewind button
EMOJI_RESTART_SOFT: str = "\u21A9\uFE0F"  # Right arrow curving left
EMOJI_RESTART_FULL: str = "\U0001F504"  # counterclockwise arrows
EMOJI_UPDATE_PIP: str = "\U0001F4E6"  # package / box
EMOJI_UPDATE_GIT: str = "\U0001F5C3\uFE0F"  # card box
EMOJI_UPDATE_ALL: str = "\U0001F310"  # globe with meridians
import asyncio
import inspect
import json
import logging
import pydoc
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    DefaultDict,
    Dict,
    List,
    Optional,
    Set,
    Type,
    Union,
)

import discord

from .constants import (
    DATA_GUILD_FILE_OPTIONS,
    DEFAULT_BOT_ICON,
    DEFAULT_FOOTER_TEXT,
    MUSICBOT_EMBED_COLOR_ERROR,
    MUSICBOT_EMBED_COLOR_NORMAL,
)
from .i18n import _D
from .json import Json
from .utils import _get_variable

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .autoplaylist import AutoPlaylist
    from .bot import MusicBot
    from .config import Config

DiscordChannels = Union[
    discord.TextChannel,
    discord.VoiceChannel,
    discord.StageChannel,
    discord.DMChannel,
    discord.GroupChannel,
]


class GuildAsyncEvent(asyncio.Event):
    """
    Simple extension of asyncio.Event() to provide a boolean flag for activity.
    """

    def __init__(self) -> None:
        """
        Create an event with an activity flag.
        """
        super().__init__()
        self._event_active: bool = False

    def is_active(self) -> bool:
        """Reports activity state"""
        return self._event_active

    def activate(self) -> None:
        """Sets the event's active flag."""
        self._event_active = True

    def deactivate(self) -> None:
        """Unset the event's active flag."""
        self._event_active = False


class GuildSpecificData:
    """
    A typed collection of data specific to each guild/discord server.
    """

    def __init__(self, bot: "MusicBot") -> None:
        """
        Initialize a managed server specific data set.
        """
        # Members for internal use only.
        self._ssd: DefaultDict[int, GuildSpecificData] = bot.server_data
        self._bot_config: Config = bot.config
        self._bot: MusicBot = bot
        self._guild_id: int = 0
        self._guild_name: str = ""
        self._command_prefix: str = ""
        self._prefix_history: Set[str] = set()
        self._events: DefaultDict[str, GuildAsyncEvent] = defaultdict(GuildAsyncEvent)
        self._file_lock: asyncio.Lock = asyncio.Lock()
        self._loading_lock: asyncio.Lock = asyncio.Lock()
        self._is_file_loaded: bool = False

        # Members below are available for public use.
        self.last_np_msg: Optional[discord.Message] = None
        self.last_played_song_subject: str = ""
        self.follow_user: Optional[discord.Member] = None
        self.auto_join_channel: Optional[
            Union[discord.VoiceChannel, discord.StageChannel]
        ] = None
        self.autoplaylist: AutoPlaylist = self._bot.playlist_mgr.get_default()
        self.current_playing_url: str = ""
        self.lang_code: str = ""

        # create a task to load any persistent guild options.
        # in theory, this should work out fine.
        bot.create_task(self.load_guild_options_file(), name="MB_LoadGuildOptions")
        bot.create_task(self.autoplaylist.load(), name="MB_LoadAPL")

    def is_ready(self) -> bool:
        """A status indicator for fully loaded server data."""
        return self._is_file_loaded and self._guild_id != 0

    def _lookup_guild_id(self) -> int:
        """
        Looks up guild.id used to create this instance of GuildSpecificData
        Will return 0 if for some reason lookup fails.
        """
        for key, val in self._ssd.items():
            if val == self:
                guild = discord.utils.find(
                    lambda m: m.id == key,  # pylint: disable=cell-var-from-loop
                    self._bot.guilds,
                )
                if guild:
                    self._guild_name = guild.name
                return key
        return 0

    async def get_played_history(self) -> Optional["AutoPlaylist"]:
        """Get the history playlist for this guild, if enabled."""
        if not self._bot.config.enable_queue_history_guilds:
            return None

        if not self.is_ready():
            return None

        pl = self._bot.playlist_mgr.get_playlist(f"history-{self._guild_id}.txt")
        pl.create_file()
        if not pl.loaded:
            await pl.load()
        return pl

    @property
    def guild_id(self) -> int:
        """Guild ID if available, may return 0 before loading is complete."""
        return self._guild_id

    @property
    def command_prefix(self) -> str:
        """
        If per-server prefix is enabled, and the server has a specific
        command prefix, it will be returned.
        Otherwise the default command prefix is returned from MusicBot config.
        """
        if self._bot_config.enable_options_per_guild:
            if self._command_prefix:
                return self._command_prefix
        return self._bot_config.command_prefix

    @command_prefix.setter
    def command_prefix(self, value: str) -> None:
        """Set the value of command_prefix"""
        if not value:
            raise ValueError("Cannot set an empty prefix.")

        # update prefix history
        if not self._command_prefix:
            self._prefix_history.add(self._bot_config.command_prefix)
        else:
            self._prefix_history.add(self._command_prefix)

        # set prefix value
        self._command_prefix = value

        # clean up history buffer if needed.
        if len(self._prefix_history) > 3:
            self._prefix_history.pop()

    @property
    def command_prefix_list(self) -> List[str]:
        """
        Get the prefix list for this guild.
        It includes a history of prefix changes since last restart as well.
        """
        history = list(self._prefix_history)

        # add self mention to invoke list.
        if self._bot_config.commands_via_mention and self._bot.user:
            history.append(f"<@{self._bot.user.id}>")

        # Add current prefix to list.
        if self._command_prefix:
            history = [self._command_prefix] + history
        else:
            history = [self._bot_config.command_prefix] + history

        return history

    def get_event(self, name: str) -> GuildAsyncEvent:
        """
        Gets an event by the given `name` or otherwise creates and stores one.
        """
        return self._events[name]

    async def load_guild_options_file(self) -> None:
        """
        Load a JSON file from the server's data directory that contains
        server-specific options intended to persist through shutdowns.
        This method only supports per-server command prefix currently.
        """
        if self._loading_lock.locked():
            return

        async with self._loading_lock:
            if self._guild_id == 0:
                self._guild_id = self._lookup_guild_id()
                if self._guild_id == 0:
                    log.error(
                        "Cannot load data for guild with ID 0. This is likely a bug in the code!"
                    )
                    return

            opt_file = self._bot_config.data_path.joinpath(
                str(self._guild_id), DATA_GUILD_FILE_OPTIONS
            )
            if not opt_file.is_file():
                log.debug(
                    "No file for guild %(id)s/%(name)s",
                    {"id": self._guild_id, "name": self._guild_name},
                )
                self._is_file_loaded = True
                return

            async with self._file_lock:
                try:
                    log.debug(
                        "Loading guild data for guild with ID:  %(id)s/%(name)s",
                        {"id": self._guild_id, "name": self._guild_name},
                    )
                    options = Json(opt_file)
                    self._is_file_loaded = True
                except OSError:
                    log.exception(
                        "An OS error prevented reading guild data file:  %s",
                        opt_file,
                    )
                    return

            self.lang_code = options.get("language", "")

            guild_prefix = options.get("command_prefix", None)
            if guild_prefix:
                self._command_prefix = guild_prefix
                log.info(
                    "Guild %(id)s/%(name)s has custom command prefix: %(prefix)s",
                    {
                        "id": self._guild_id,
                        "name": self._guild_name,
                        "prefix": self._command_prefix,
                    },
                )

            guild_playlist = options.get("auto_playlist", None)
            if guild_playlist:
                self.autoplaylist = self._bot.playlist_mgr.get_playlist(guild_playlist)
                await self.autoplaylist.load()

    async def save_guild_options_file(self) -> None:
        """
        Save server-specific options, like the command prefix, to a JSON
        file in the server's data directory.
        """
        if self._guild_id == 0:
            log.error(
                "Cannot save data for guild with ID 0. This is likely a bug in the code!"
            )
            return

        opt_file = self._bot_config.data_path.joinpath(
            str(self._guild_id), DATA_GUILD_FILE_OPTIONS
        )

        auto_playlist = None
        if self.autoplaylist is not None:
            auto_playlist = self.autoplaylist.filename

        # Prepare a dictionary to store our options.
        opt_dict = {
            "command_prefix": self._command_prefix,
            "auto_playlist": auto_playlist,
            "language": self.lang_code,
        }

        async with self._file_lock:
            try:
                with open(opt_file, "w", encoding="utf8") as fh:
                    fh.write(json.dumps(opt_dict))
            except OSError:
                log.exception("Could not save guild specific data due to OS Error.")
            except (TypeError, ValueError):
                log.exception(
                    "Failed to serialize guild specific data due to invalid data."
                )


class SkipState:
    __slots__ = ["skippers", "skip_msgs"]

    def __init__(self) -> None:
        """
        Manage voters and their ballots for fair MusicBot track skipping.
        This creates a set of discord.Message and a set of member IDs to
        enable counting votes for skipping a song.
        """
        self.skippers: Set[int] = set()
        self.skip_msgs: Set[discord.Message] = set()

    @property
    def skip_count(self) -> int:
        """
        Get the number of authors who requested skip.
        """
        return len(self.skippers)

    def reset(self) -> None:
        """
        Clear the vote counting sets.
        """
        self.skippers.clear()
        self.skip_msgs.clear()

    def add_skipper(self, skipper_id: int, msg: "discord.Message") -> int:
        """
        Add a message and the author's ID to the skip vote.
        """
        self.skippers.add(skipper_id)
        self.skip_msgs.add(msg)
        return self.skip_count


class MusicBotResponse(discord.Embed):
    """
    Base class for all messages generated by MusicBot.
    Allows messages to be switched easily between embed and plain-text.
    """

    def __init__(
        self,
        content: str,
        title: Optional[str] = None,
        codeblock: Optional[str] = None,
        reply_to: Optional[discord.Message] = None,
        send_to: Optional[DiscordChannels] = None,
        sent_from: Optional[discord.abc.Messageable] = None,
        color_hex: str = MUSICBOT_EMBED_COLOR_NORMAL,
        files: Optional[List[discord.File]] = None,
        delete_after: Union[None, int, float] = None,
        force_text: bool = False,
        force_embed: bool = False,
        no_footer: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Creates an embed-like response object.

        :param: content:  The primary content, the description in the embed.
        :param: codeblock:  A string used for syntax highlighter markdown.
                            Setting this parameter will format content at display time.
        :param: reply_to:  A message to reply to with this response.
        :param: send_to:  A destination for the message.
        :param: sent_from:  A channel where this response can be sent to if send_to fails.
                            This is useful for DM with strict perms.
        :param: color_hex:  A hex color string used only for embed accent color.
        :param: files:      A list of discord.File objects to send.
        :param: delete_after:   A time limit to wait before deleting the response from discord.
                                Only used if message delete options are enabled.
        :param: force_text:  Regardless of settings, this response should be text-only.
        :param: force_embed: Regardless of settings, this response should be embed-only.
        :param: no_footer:   Disable the embed footer entirely. Only used on Embeds.
        """
        self.content = content
        self.codeblock = codeblock
        self.reply_to = reply_to
        self.send_to = send_to
        self.sent_from = sent_from
        self.force_text = force_text
        self.force_embed = force_embed
        self.delete_after = delete_after
        self.files = files if files is not None else []

        super().__init__(
            title=title,
            color=discord.Colour.from_str(color_hex),
            **kwargs,
        )
        if not no_footer:
            self.set_footer(
                text=DEFAULT_FOOTER_TEXT,
                icon_url=DEFAULT_BOT_ICON,
            )
        # overload the original description with our formatting property.
        # yes, this is cursed and I don't like doing it, but it defers format.
        setattr(self, "description", getattr(self, "overload_description"))

    @property
    def overload_description(self) -> str:
        """
        Overload the description attribute to defer codeblock formatting.
        """
        if self.codeblock:
            return f"```{self.codeblock}\n{self.content}```"
        return self.content

    def to_markdown(self, ssd_: Optional[GuildSpecificData] = None) -> str:
        """
        Converts the embed to a markdown text.
        Does not include thumbnail and image urls.
        Embeds may have more content than text messages will allow!
        """
        url = ""
        title = ""
        descr = ""
        image = ""
        fields = ""
        if self.title:
            # TRANSLATORS: text-only format for embed title.
            title = _D("## %(title)s\n", ssd_) % {"title": self.title}
        if self.description:
            # TRANSLATORS: text-only format for embed description.
            descr = _D("%(content)s\n", ssd_) % {"content": self.description}
        if self.url:
            # TRANSLATORS: text-only format for embed url.
            url = _D("%(url)s\n", ssd_) % {"url": self.url}

        for field in self.fields:
            if field.value:
                if field.name:
                    # TRANSLATORS: text-only format for embed field name an value.
                    fields += _D("**%(name)s** %(value)s\n", ssd_) % {
                        "name": field.name,
                        "value": field.value,
                    }
                else:
                    # TRANSLATORS: text-only format for embed field without a name.
                    fields += _D("%(value)s\n", ssd_) % {"value": field.value}

        # only pick one image if both thumbnail and image are set,
        if self.image:
            # TRANSLATORS: text-only format for embed image or thumbnail.
            image = _D("%(url)s", ssd_) % {"url": self.image.url}
        elif self.thumbnail:
            image = _D("%(url)s", ssd_) % {"url": self.thumbnail.url}

        return _D(
            # TRANSLATORS: text-only format template for embeds converted to markdown.
            "%(title)s%(content)s%(url)s%(fields)s%(image)s",
            ssd_,
        ) % {
            "title": title,
            "content": descr,
            "url": url,
            "fields": fields,
            "image": image,
        }


class Response(MusicBotResponse):
    """Response"""

    def __init__(self, content: str, **kwargs: Any) -> None:
        super().__init__(content=content, **kwargs)


class ErrorResponse(MusicBotResponse):
    """An error message to send to discord."""

    def __init__(self, content: str, **kwargs: Any) -> None:
        if "color_hex" in kwargs:
            kwargs.pop("color_hex")

        super().__init__(
            content=content, color_hex=MUSICBOT_EMBED_COLOR_ERROR, **kwargs
        )


class Serializer(json.JSONEncoder):
    def default(self, o: "Serializable") -> Any:
        """
        Default method used by JSONEncoder to return serializable data for
        the given object or Serializable in `o`
        """
        if hasattr(o, "__json__"):
            return o.__json__()

        return super().default(o)

    @classmethod
    def deserialize(cls, data: Dict[str, Any]) -> Any:
        """
        Read a simple JSON dict for a valid class signature, and pass the
        simple dict on to a _deserialize function in the signed class.
        """
        if all(x in data for x in Serializable.CLASS_SIGNATURE):
            # log.debug("Deserialization requested for %s", data)
            factory = pydoc.locate(data["__module__"] + "." + data["__class__"])
            # log.debug("Found object %s", factory)
            if factory and issubclass(factory, Serializable):  # type: ignore[arg-type]
                # log.debug("Deserializing %s object", factory)
                return factory._deserialize(  # type: ignore[attr-defined]
                    data["data"], **cls._get_vars(factory._deserialize)  # type: ignore[attr-defined]
                )

        return data

    @classmethod
    def _get_vars(cls, func: Callable[..., Any]) -> Dict[str, Any]:
        """
        Inspect argument specification for given callable `func` and attempt
        to inject it's named parameters by inspecting the calling frames for
        locals which match the parameter names.
        """
        # log.debug("Getting vars for %s", func)
        params = inspect.signature(func).parameters.copy()
        args = {}
        # log.debug("Got %s", params)

        for name, param in params.items():
            # log.debug("Checking arg %s, type %s", name, param.kind)
            if param.kind is param.POSITIONAL_OR_KEYWORD and param.default is None:
                # log.debug("Using var %s", name)
                args[name] = _get_variable(name)
                # log.debug("Collected var for arg '%s': %s", name, args[name])

        return args


class Serializable:
    CLASS_SIGNATURE = ("__class__", "__module__", "data")

    def _enclose_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Helper used by child instances of Serializable that includes class signature
        for the Serializable object.
        Intended to be called from __json__ methods of child instances.
        """
        return {
            "__class__": self.__class__.__qualname__,
            "__module__": self.__module__,
            "data": data,
        }

    # Perhaps convert this into some sort of decorator
    @staticmethod
    def _bad(arg: str) -> None:
        """
        Wrapper used by assertions in Serializable classes to enforce required arguments.

        :param: arg:  the parameter name being enforced.

        :raises: TypeError  when given `arg` is None in calling frame.
        """
        raise TypeError(f"Argument '{arg}' must not be None")

    def serialize(self, *, cls: Type[Serializer] = Serializer, **kwargs: Any) -> str:
        """
        Simple wrapper for json.dumps with Serializer instance support.
        """
        return json.dumps(self, cls=cls, **kwargs)

    def __json__(self) -> Optional[Dict[str, Any]]:
        """
        Serialization method to be implemented by derived classes.
        Should return a simple dictionary representing the Serializable
        class and its data/state, using only built-in types.
        """
        raise NotImplementedError

    @classmethod
    def _deserialize(
        cls: Type["Serializable"], raw_json: Dict[str, Any], **kwargs: Any
    ) -> Any:
        """
        Deserialization handler, to be implemented by derived classes.
        Should construct and return a valid Serializable child instance or None.

        :param: raw_json:  data from json.loads() using built-in types only.
        """
        raise NotImplementedError
import asyncio
import copy
import datetime
import functools
import hashlib
import importlib
import logging
import os
import pathlib
from collections import UserDict
from concurrent.futures import ThreadPoolExecutor
from pprint import pformat
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import aiohttp
import yt_dlp as youtube_dl  # type: ignore[import-untyped]
from yt_dlp.networking.exceptions import (  # type: ignore[import-untyped]
    NoSupportingHandlers,
)
from yt_dlp.utils import DownloadError  # type: ignore[import-untyped]
from yt_dlp.utils import UnsupportedError

from .constants import DEFAULT_MAX_INFO_DL_THREADS, DEFAULT_MAX_INFO_REQUEST_TIMEOUT
from .exceptions import ExtractionError, MusicbotException
from .spotify import Spotify
from .ytdlp_oauth2_plugin import enable_ytdlp_oauth2_plugin

if TYPE_CHECKING:
    from multidict import CIMultiDictProxy

    from .bot import MusicBot

    # Explicit compat with python 3.8
    YUserDict = UserDict[str, Any]
else:
    YUserDict = UserDict


log = logging.getLogger(__name__)

# Immutable dict is needed, because something is modifying the 'outtmpl' value. I suspect it being ytdl, but I'm not sure.
ytdl_format_options_immutable = MappingProxyType(
    {
        "format": "bestaudio/best",
        "outtmpl": "%(extractor)s-%(id)s-%(title)s-%(qhash)s.%(ext)s",
        "restrictfilenames": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "quiet": True,
        "no_warnings": True,
        # extract_flat speeds up extract_info by only listing playlist entries rather than extracting them as well.
        "extract_flat": "in_playlist",
        "default_search": "auto",
        "source_address": "0.0.0.0",
        "usenetrc": True,
        "no_color": True,
    }
)


# Fuck your useless bugreports message that gets two link embeds and confuses users
youtube_dl.utils.bug_reports_message = lambda: ""

"""
    Alright, here's the problem.  To catch youtube-dl errors for their useful information, I have to
    catch the exceptions with `ignoreerrors` off.  To not break when ytdl hits a dumb video
    (rental videos, etc), I have to have `ignoreerrors` on.  I can change these whenever, but with async
    that's bad.  So I need multiple ytdl objects.

"""


class Downloader:
    def __init__(self, bot: "MusicBot") -> None:
        """
        Set up YoutubeDL and related config as well as a thread pool executor
        to run concurrent extractions.
        """
        self.bot: MusicBot = bot
        self.download_folder: pathlib.Path = bot.config.audio_cache_path
        # NOTE: this executor may not be good for long-running downloads...
        self.thread_pool = ThreadPoolExecutor(
            max_workers=DEFAULT_MAX_INFO_DL_THREADS,
            thread_name_prefix="MB_Downloader",
        )

        # force ytdlp and HEAD requests to use the same UA string.
        # If the constant is set, use that, otherwise use dynamic selection.
        if bot.config.ytdlp_user_agent:
            ua = bot.config.ytdlp_user_agent
            log.warning("Forcing YTDLP to use User Agent:  %s", ua)
        else:
            ua = youtube_dl.utils.networking.random_user_agent()
        self.http_req_headers = {"User-Agent": ua}
        # Copy immutable dict and use the mutable copy for everything else.
        ytdl_format_options = ytdl_format_options_immutable.copy()
        ytdl_format_options["http_headers"] = self.http_req_headers

        # check if we should apply a cookies file to ytdlp.
        if bot.config.cookies_path.is_file():
            log.info(
                "MusicBot will use cookies for yt-dlp from:  %s",
                bot.config.cookies_path,
            )
            ytdl_format_options["cookiefile"] = bot.config.cookies_path

        if bot.config.ytdlp_proxy:
            log.info("Yt-dlp will use your configured proxy server.")
            ytdl_format_options["proxy"] = bot.config.ytdlp_proxy

        if bot.config.ytdlp_use_oauth2:
            # set the login info so oauth2 is prompted.
            ytdl_format_options["username"] = "mb_oauth2"
            ytdl_format_options["password"] = ""
            # ytdl_format_options["extractor_args"] = {
            #    "youtubetab": {"skip": ["authcheck"]}
            # }

            # check if the original plugin is installed, and use it instead of ours.
            # It's worth doing this because our version might fail to work,
            # even if the original causes infinite loop hangs while auth is pending...
            try:
                oauth_spec = importlib.util.find_spec(
                    "yt_dlp_plugins.extractor.youtubeoauth"
                )
            except ModuleNotFoundError:
                oauth_spec = None

            if oauth_spec is not None:
                log.warning(
                    "Original OAuth2 plugin is installed and will be used instead.\n"
                    "This may cause MusicBot to not close completely, or hang pending authorization!\n"
                    "To close MusicBot, you must manually Kill the MusicBot process!\n"
                    "Yt-dlp is being set to show warnings and other log messages, to show the Auth code.\n"
                    "Uninstall the yt-dlp-youtube-oauth2 package to use integrated OAuth2 features instead."
                )
                ytdl_format_options["quiet"] = False
                ytdl_format_options["no_warnings"] = False
            else:
                enable_ytdlp_oauth2_plugin(self.bot.config)

        if self.download_folder:
            # print("setting template to " + os.path.join(download_folder, otmpl))
            otmpl = ytdl_format_options["outtmpl"]
            ytdl_format_options["outtmpl"] = os.path.join(
                self.download_folder, str(otmpl)
            )

        self.unsafe_ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
        self.safe_ytdl = youtube_dl.YoutubeDL(
            {**ytdl_format_options, "ignoreerrors": True}
        )

    @property
    def ytdl(self) -> youtube_dl.YoutubeDL:
        """Get the Safe (errors ignored) instance of YoutubeDL."""
        return self.safe_ytdl

    @property
    def cookies_enabled(self) -> bool:
        """
        Get status of cookiefile option in ytdlp objects.
        """
        return all(
            "cookiefile" in ytdl.params for ytdl in [self.safe_ytdl, self.unsafe_ytdl]
        )

    def enable_ytdl_cookies(self) -> None:
        """
        Set the cookiefile option on the ytdl objects.
        """
        self.safe_ytdl.params["cookiefile"] = self.bot.config.cookies_path
        self.unsafe_ytdl.params["cookiefile"] = self.bot.config.cookies_path

    def disable_ytdl_cookies(self) -> None:
        """
        Remove the cookiefile option on the ytdl objects.
        """
        del self.safe_ytdl.params["cookiefile"]
        del self.unsafe_ytdl.params["cookiefile"]

    def randomize_user_agent_string(self) -> None:
        """
        Uses ytdlp utils functions to re-randomize UA strings in YoutubeDL
        objects and header check requests.
        """
        # ignore this call if static UA is configured.
        if not self.bot.config.ytdlp_user_agent:
            return

        new_ua = youtube_dl.utils.networking.random_user_agent()
        self.unsafe_ytdl.params["http_headers"]["User-Agent"] = new_ua
        self.safe_ytdl.params["http_headers"]["User-Agent"] = new_ua
        self.http_req_headers["User-Agent"] = new_ua

    def get_url_or_none(self, url: str) -> Optional[str]:
        """
        Uses ytdl.utils.url_or_none() to validate a playable URL.
        Will also strip < and > if they are found at the start and end of a URL.
        """
        # Discord might add < and > to the URL, this strips them out if they exist.
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        u = youtube_dl.utils.url_or_none(url)

        # Just in case ytdlp changes... also strict typing.
        if isinstance(u, str):
            return u
        return None

    async def get_url_headers(self, url: str) -> Dict[str, str]:
        """
        Make an HTTP HEAD request and return response headers safe for serialization.
        Header names are converted to upper case.
        If `url` is not valid the header 'X-INVALID-URL' is set to its value.
        """
        test_url = self.get_url_or_none(url)
        headers: Dict[str, Any] = {}
        # do a HEAD request and add the headers to extraction info.
        if test_url and self.bot.session:
            try:
                head_data = await self._get_headers(
                    self.bot.session,
                    test_url,
                    timeout=DEFAULT_MAX_INFO_REQUEST_TIMEOUT,
                    req_headers=self.http_req_headers,
                )
                if not head_data:
                    raise ExtractionError("HEAD seems to have no headers...")

                # convert multidict headers to a serializable dict.
                for key in set(head_data.keys()):
                    new_key = key.upper()
                    values = head_data.getall(key)
                    if len(values) > 1:
                        headers[new_key] = values
                    else:
                        headers[new_key] = values.pop()
            except asyncio.exceptions.TimeoutError:
                log.warning("Checking media headers failed due to timeout.")
                headers = {"X-HEAD-REQ-FAILED": "1"}
            except (ExtractionError, OSError, aiohttp.ClientError):
                log.warning("Failed HEAD request for:  %s", test_url)
                log.exception("HEAD Request exception: ")
                headers = {"X-HEAD-REQ-FAILED": "1"}
        else:
            headers = {"X-INVALID-URL": url}
        return headers

    async def _get_headers(  # pylint: disable=dangerous-default-value
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        timeout: int = 10,
        allow_redirects: bool = True,
        req_headers: Dict[str, Any] = {},
    ) -> Union["CIMultiDictProxy[str]", None]:
        """
        Uses given aiohttp `session` to fetch HEAD of given `url` without making
        any checks if the URL is valid.
        If `headerfield` is set, only the given header field is returned.

        :param: timeout:  Set a different timeout for the HEAD request.
        :param: allow_redirect:  Follow "Location" headers through, on by default.
        :param: req_headers:  Set a collection of headers to send with the HEAD request.

        :returns:  A case-insensitive multidict instance, not serializable.

        :raises:  aiohttp.ClientError and derived exceptions
            For errors handled internally by aiohttp.
        :raises:  OSError
            For errors not handled by aiohttp.
        """
        req_timeout = aiohttp.ClientTimeout(total=timeout)
        async with session.head(
            url,
            timeout=req_timeout,
            allow_redirects=allow_redirects,
            headers=req_headers,
            proxy=self.bot.config.ytdlp_proxy,
        ) as response:
            return response.headers

    def _sanitize_and_log(  # pylint: disable=dangerous-default-value
        self,
        data: Dict[str, Any],
        redact_fields: List[str] = [],
    ) -> None:
        """
        Debug helper function.
        Copies data, removes some long-winded entries and logs the result data for inspection.
        """
        if log.getEffectiveLevel() > logging.DEBUG:
            return

        data = copy.deepcopy(data)
        redacted_str = "__REDACTED_FOR_CLARITY__"

        if "entries" in data:
            # cleaning up entry data to make it easier to parse in logs.
            for i, e in enumerate(data["entries"]):
                for field in redact_fields:
                    if field in e and e[field]:
                        data["entries"][i][field] = redacted_str

        for field in redact_fields:
            if field in data:
                data[field] = redacted_str

        if log.getEffectiveLevel() <= logging.EVERYTHING:  # type: ignore[attr-defined]
            log.noise("Sanitized YTDL Extraction Info (not JSON):\n%s", pformat(data))  # type: ignore[attr-defined]
        else:
            log.noise("Sanitized YTDL Extraction Info (not JSON):  %s", data)  # type: ignore[attr-defined]

    async def extract_info(
        self, song_subject: str, *args: Any, **kwargs: Any
    ) -> "YtdlpResponseDict":
        """
        Runs ytdlp.extract_info with all arguments passed to this function.
        If `song_subject` is a valid URL, extraction will add HEAD request headers.
        Resulting data is passed through ytdlp's sanitize_info and returned
        inside of a YtdlpResponseDict wrapper.

        Single-entry search results are returned as if they were top-level extractions.
        Links for spotify tracks, albums, and playlists also get special filters.

        :param: song_subject: a song url or search subject.
        :kwparam: as_stream: If we should try to queue the URL anyway and let ffmpeg figure it out.

        :returns: YtdlpResponseDict object containing sanitized extraction data.

        :raises: musicbot.exceptions.MusicbotError
            if event loop is closed and cannot be used for extraction.

        :raises: musicbot.exceptions.ExtractionError
            for errors in MusicBot's internal filtering and pre-processing of extraction queries.

        :raises: musicbot.exceptions.SpotifyError
            for issues with Musicbot's Spotify API request and data handling.

        :raises: yt_dlp.utils.YoutubeDLError
            as a base exception for any exceptions raised by yt_dlp.

        :raises: yt_dlp.networking.exceptions.RequestError
            as a base exception for any networking errors raised by yt_dlp.
        """
        # handle local media playback without ever touching ytdl and friends.
        # We do this here so auto playlist features can take advantage of this as well.
        if self.bot.config.enable_local_media and song_subject.lower().startswith(
            "file://"
        ):
            return self._return_local_media(song_subject)

        # Hash the URL for use as a unique ID in file paths.
        # but ignore services with multiple URLs for the same media.
        song_subject_hash = ""
        if (
            "youtube.com" not in song_subject.lower()
            and "youtu.be" not in song_subject.lower()
        ):
            md5 = hashlib.md5()  # nosec
            md5.update(song_subject.encode("utf8"))
            song_subject_hash = md5.hexdigest()[-8:]

        # Use ytdl or one of our custom integration to get info.
        data = await self._filtered_extract_info(
            song_subject,
            *args,
            **kwargs,
            # just (ab)use a ytdlp internal thing, a tiny bit...
            extra_info={
                "qhash": song_subject_hash,
            },
        )

        if not data:
            raise ExtractionError("Song info extraction returned no data.")

        # always get headers for our downloadable.
        headers = await self.get_url_headers(data.get("url", song_subject))

        # if we made it here, put our request data into the extraction.
        data["__input_subject"] = song_subject
        data["__header_data"] = headers or None
        data["__expected_filename"] = self.ytdl.prepare_filename(data)

        # ensure the UA is randomized with each new request if not set static.
        self.randomize_user_agent_string()

        """
        # disabled since it is only needed for working on extractions.
        # logs data only for debug and higher verbosity levels.
        self._sanitize_and_log(
            data,
            # these fields are here because they are often very lengthy.
            # they could be useful to others, devs should change redact_fields
            # as needed, but maybe not commit these changes
            redact_fields=["automatic_captions", "formats", "heatmap"],
        )
        """
        return YtdlpResponseDict(data)

    async def _filtered_extract_info(
        self, song_subject: str, *args: Any, **kwargs: Any
    ) -> Dict[str, Any]:
        """
        The real logic behind Downloader.extract_info()
        This function uses an event loop executor to make the call to
        YoutubeDL.extract_info() via the unsafe instance, which will issue errors.

        :param: song_subject: a song url or search subject.
        :kwparam: as_stream: If we should try to queue the URL anyway and let ffmpeg figure it out.

        :returns: Dictionary of data returned from extract_info() or other
            integration. Serialization ready.

        :raises: musicbot.exceptions.MusicbotError
            if event loop is closed and cannot be used for extraction.

        :raises: musicbot.exceptions.ExtractionError
            for errors in MusicBot's internal filtering and pre-processing of extraction queries.

        :raises: musicbot.exceptions.SpotifyError
            for issues with Musicbot's Spotify API request and data handling.

        :raises: yt_dlp.utils.YoutubeDLError
            as a base exception for any exceptions raised by yt_dlp.

        :raises: yt_dlp.networking.exceptions.RequestError
            as a base exception for any networking errors raised by yt_dlp.
        """
        log.noise(  # type: ignore[attr-defined]
            "Called extract_info with:  '%(subject)s', %(args)s, %(kws)s",
            {"subject": song_subject, "args": args, "kws": kwargs},
        )
        as_stream_url = kwargs.pop("as_stream", False)

        # check if loop is closed and exit.
        if (self.bot.loop and self.bot.loop.is_closed()) or not self.bot.loop:
            log.warning(
                "Cannot run extraction, loop is closed. (This is normal on shutdowns.)"
            )
            raise MusicbotException("Cannot continue extraction, event loop is closed.")

        # handle extracting spotify links before ytdl get a hold of them.
        if (
            "open.spotify.com" in song_subject.lower()
            and self.bot.config.spotify_enabled
            and self.bot.spotify is not None
        ):
            if not Spotify.is_url_supported(song_subject):
                raise ExtractionError("Spotify URL is invalid or not supported.")

            process = bool(kwargs.get("process", True))
            download = kwargs.get("download", True)

            # return only basic ytdl-flavored data from the Spotify API.
            # This call will not fetch all tracks in playlists or albums.
            if not process and not download:
                data = await self.bot.spotify.get_spotify_ytdl_data(song_subject)
                return data

            # modify args to have ytdl return search data, only for singular tracks.
            # for albums & playlists, we want to return full playlist data rather than partial as above.
            if process:
                data = await self.bot.spotify.get_spotify_ytdl_data(
                    song_subject, process
                )
                if data["_type"] == "url":
                    song_subject = data["search_terms"]
                elif data["_type"] == "playlist":
                    return data

        # Actually call YoutubeDL extract_info.
        try:
            data = await self.bot.loop.run_in_executor(
                self.thread_pool,
                functools.partial(
                    self.unsafe_ytdl.extract_info, song_subject, *args, **kwargs
                ),
            )
        except DownloadError as e:
            if not as_stream_url:
                raise ExtractionError(
                    "Error in yt-dlp while downloading data: %(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

            log.exception("Download Error with stream URL")
            if e.exc_info[0] == UnsupportedError:
                # ytdl doesn't support it but it could be stream-able...
                song_url = self.get_url_or_none(song_subject)
                if song_url:
                    log.debug("Assuming content is a direct stream")
                    data = {
                        "title": song_subject,
                        "extractor": None,
                        "url": song_url,
                        "__force_stream": True,
                    }
                else:
                    raise ExtractionError("Cannot stream an invalid URL.") from e

            else:
                raise ExtractionError(
                    "Error in yt-dlp while downloading data: %(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e
        except NoSupportingHandlers:
            # due to how we allow search service strings we can't just encode this by default.
            # on the other hand, this method prevents cmd_stream from taking search strings.
            log.noise(  # type: ignore[attr-defined]
                "Caught NoSupportingHandlers, trying again after replacing colon with space."
            )
            song_subject = song_subject.replace(":", " ")
            # TODO: maybe this also needs some exception handling...
            data = await self.bot.loop.run_in_executor(
                self.thread_pool,
                functools.partial(
                    self.unsafe_ytdl.extract_info, song_subject, *args, **kwargs
                ),
            )

        # make sure the ytdlp data is serializable to make it more predictable.
        data = self.ytdl.sanitize_info(data)

        # Extractor youtube:search returns a playlist-like result, usually with one entry
        # when searching via a play command.
        # Combine the entry dict with the info dict as if it was a top-level extraction.
        # This prevents single-entry searches being processed like a playlist later.
        # However we must preserve the list behavior when using cmd_search.
        if (
            data.get("extractor", "").startswith("youtube:search")
            and len(data.get("entries", [])) == 1
            and isinstance(data.get("entries", None), list)
            and data.get("playlist_count", 0) == 1
            and not song_subject.startswith("ytsearch")
        ):
            log.noise(  # type: ignore[attr-defined]
                "Extractor youtube:search returned single-entry result, replacing base info with entry info."
            )
            entry_info = copy.deepcopy(data["entries"][0])
            for key in entry_info:
                data[key] = entry_info[key]
            del data["entries"]

        return data

    async def safe_extract_info(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Awaits an event loop executor to call extract_info in a thread pool.
        Uses an instance of YoutubeDL with errors explicitly ignored to
        call extract_info with all arguments passed to this function.
        """
        log.noise(  # type: ignore[attr-defined]
            "Called safe_extract_info with:  %(args)s, %(kws)s",
            {"args": args, "kws": kwargs},
        )
        return await self.bot.loop.run_in_executor(
            self.thread_pool,
            functools.partial(self.safe_ytdl.extract_info, *args, **kwargs),
        )

    def _return_local_media(self, song_subject: str) -> "YtdlpResponseDict":
        """Verifies local media files and returns suitable data for local entries."""
        filename = song_subject[7:]
        media_path = self.bot.config.media_file_dir.resolve()
        unclean_path = media_path.joinpath(filename).resolve()
        if os.path.commonprefix([media_path, unclean_path]) == str(media_path):
            local_file_path = unclean_path
        else:
            local_file_path = media_path.joinpath(pathlib.Path(filename).name)
        corrected_fie_uri = str(local_file_path).replace(str(media_path), "file://")

        if not local_file_path.is_file():
            raise MusicbotException("The local media file could not be found.")

        return YtdlpResponseDict(
            {
                "__input_subject": song_subject,
                "__header_data": None,
                "__expected_filename": local_file_path,
                "_type": "local",
                # "original_url": song_subject,
                "extractor": "local:musicbot",
                "extractor_key": "LocalMediaMusicBot",
                # Getting a "good" title for the track will take some serious consideration...
                "title": local_file_path.name,
                "url": corrected_fie_uri,
            }
        )


class YtdlpResponseDict(YUserDict):
    """
    UserDict wrapper for ytdlp extraction data with helpers for easier data reuse.
    The dict features are available only for compat with existing code.
    Use of the dict subscript notation is not advised and could/should be
    removed in the future, in favor of typed properties and processing
    made available herein.

    See ytdlp doc string in InfoExtractor for info on data:
    https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        super().__init__(data)
        self._propagate_entry_data()

    def _propagate_entry_data(self) -> None:
        """ensure the `__input_subject` key is set on all child entries."""
        subject = self.get("__input_subject", None)
        if not subject:
            log.warning("Missing __input_subject from YtdlpResponseDict")

        entries = self.data.get("entries", [])
        if not isinstance(entries, list):
            log.warning(
                "Entries is not a list in YtdlpResponseDict, set process=True to avoid this."
            )
            return

        for entry in self.data.get("entries", []):
            if "__input_subject" not in entry:
                entry["__input_subject"] = subject

    def get_entries_dicts(self) -> List[Dict[str, Any]]:
        """will return entries as-is from data or an empty list if no entries are set."""
        entries = self.data.get("entries", [])
        if isinstance(entries, list):
            return entries
        return []

    def get_entries_objects(self) -> List["YtdlpResponseDict"]:
        """will iterate over entries and return list of YtdlpResponseDicts"""
        return [YtdlpResponseDict(e) for e in self.get_entries_dicts()]

    def get_entry_dict_at(self, idx: int) -> Optional[Dict[str, Any]]:
        """Get a dict from "entries" at the given index or None."""
        entries = self.get_entries_dicts()
        if entries:
            try:
                return entries[idx]
            except IndexError:
                pass
        return None

    def get_entry_object_at(self, idx: int) -> Optional["YtdlpResponseDict"]:
        """Get a YtdlpResponseDict for given entry or None."""
        e = self.get_entry_dict_at(idx)
        if e:
            return YtdlpResponseDict(e)
        return None

    def get_playable_url(self) -> str:
        """
        Get a playable URL for any given response type.
        will try 'url', then 'webpage_url'
        """
        if self.ytdl_type == "video":
            if not self.webpage_url:
                return self.url
            return self.webpage_url

        if not self.url:
            return self.webpage_url
        return self.url

    def http_header(self, header_name: str, default: Any = None) -> Any:
        """Get HTTP Header information if it is available."""
        headers = self.data.get("__header_data", None)
        if headers:
            return headers.get(
                header_name.upper(),
                default,
            )
        return default

    @property
    def input_subject(self) -> str:
        """Get the input subject used to create this data."""
        subject = self.data.get("__input_subject", "")
        if isinstance(subject, str):
            return subject
        return ""

    @property
    def expected_filename(self) -> Optional[str]:
        """get expected filename for this info data, or None if not available"""
        fn = self.data.get("__expected_filename", None)
        if isinstance(fn, str) and fn:
            return fn
        return None

    @property
    def entry_count(self) -> int:
        """count of existing entries if available or 0"""
        if self.has_entries:
            return len(self.data["entries"])
        return 0

    @property
    def has_entries(self) -> bool:
        """bool status if iterable entries are present."""
        if "entries" not in self.data:
            return False
        if not isinstance(self.data["entries"], list):
            return False
        return bool(len(self.data["entries"]))

    @property
    def thumbnail_url(self) -> str:
        """
        Get a thumbnail url if available, or create one if possible, otherwise returns an empty string.
        Note, the URLs returned from this function may be time-sensitive.
        In the case of spotify, URLs may not last longer than a day.
        """
        turl = self.data.get("thumbnail", None)
        # if we have a thumbnail url, clean it up if needed and return it.
        if isinstance(turl, str) and turl:
            return turl

        # Check if we have a thumbnails key and pick a thumb from it.
        # TODO: maybe loop over these finding the largest / highest priority entry instead?.
        thumbs = self.data.get("thumbnails", [])
        if thumbs:
            if self.extractor.startswith("youtube"):
                # youtube seems to set the last list entry to the largest.
                turl = thumbs[-1].get("url")

            # spotify images are in size descending order, reverse of youtube.
            elif len(thumbs):
                turl = thumbs[0].get("url")

            if isinstance(turl, str) and turl:
                return turl

        # if all else fails, try to make a URL on our own.
        if self.extractor.startswith("youtube"):
            if self.video_id:
                return f"https://i.ytimg.com/vi/{self.video_id}/maxresdefault.jpg"

        # Extractor Bandcamp:album unfortunately does not give us thumbnail(s)
        # tracks do have thumbs, but process does not return them while "extract_flat" is enabled.
        # we don't get enough data with albums to make a thumbnail URL either.
        # really this is an upstream issue with ytdlp, and should be patched there.
        # See: BandcampAlbumIE and add missing thumbnail: self._og_search_thumbnail(webpage)

        return ""

    @property
    def ytdl_type(self) -> str:
        """returns value for data key '_type' or empty string"""
        t = self.data.get("_type", "")
        if isinstance(t, str) and t:
            return t
        return ""

    @property
    def extractor(self) -> str:
        """returns value for data key 'extractor' or empty string"""
        e = self.data.get("extractor", "")
        if isinstance(e, str) and e:
            return e
        return ""

    @property
    def extractor_key(self) -> str:
        """returns value for data key 'extractor_key' or empty string"""
        ek = self.data.get("extractor_key", "")
        if isinstance(ek, str) and ek:
            return ek
        return ""

    @property
    def url(self) -> str:
        """returns value for data key 'url' or empty string"""
        u = self.data.get("url", "")
        if isinstance(u, str) and u:
            return u
        return ""

    @property
    def webpage_url(self) -> str:
        """returns value for data key 'webpage_url' or None"""
        u = self.data.get("webpage_url", "")
        if isinstance(u, str) and u:
            return u
        return ""

    @property
    def webpage_basename(self) -> Optional[str]:
        """returns value for data key 'webpage_url_basename' or None"""
        bn = self.data.get("webpage_url_basename", None)
        if isinstance(bn, str) and bn:
            return bn
        return None

    @property
    def webpage_domain(self) -> Optional[str]:
        """returns value for data key 'webpage_url_domain' or None"""
        d = self.data.get("webpage_url_domain", None)
        if isinstance(d, str) and d:
            return d
        return None

    @property
    def original_url(self) -> Optional[str]:
        """returns value for data key 'original_url' or None"""
        u = self.data.get("original_url", None)
        if isinstance(u, str) and u:
            return u
        return None

    @property
    def video_id(self) -> str:
        """returns the id if it exists or empty string."""
        i = self.data.get("id", "")
        if isinstance(i, str) and i:
            return i
        return ""

    @property
    def title(self) -> str:
        """returns title value if it exists, empty string otherwise."""
        # Note: seemingly all processed data should have "title" key
        # entries in data may also have "fulltitle" and "playlist_title" keys.
        t = self.data.get("title", "")
        if isinstance(t, str) and t:
            return t
        return ""

    @property
    def playlist_count(self) -> int:
        """returns the playlist_count value if it exists, or 0"""
        c = self.data.get("playlist_count", 0)
        if isinstance(c, int):
            return c
        return 0

    @property
    def duration(self) -> float:
        """returns duration in seconds if available, or 0"""
        try:
            return float(self.data.get("duration", 0))
        except (ValueError, TypeError):
            log.noise(  # type: ignore[attr-defined]
                "Warning, duration error for: %(url)s",
                {"url": self.original_url},
                exc_info=True,
            )
            return 0.0

    @property
    def duration_td(self) -> datetime.timedelta:
        """
        Returns duration as a datetime.timedelta object.
        May contain 0 seconds duration.
        """
        t = self.duration or 0
        return datetime.timedelta(seconds=t)

    @property
    def is_live(self) -> bool:
        """return is_live key status or False if not found."""
        # Can be true, false, or None if state is unknown.
        # Here we assume unknown is not live.
        live = self.data.get("is_live", False)
        if isinstance(live, bool):
            return live
        return False

    @property
    def is_stream(self) -> bool:
        """indicate if this response is a streaming resource."""
        if self.is_live:
            return True

        # So live_status can be one of:
        # None (=unknown), 'is_live', 'is_upcoming', 'was_live', 'not_live',
        # or 'post_live' (was live, but VOD is not yet processed)
        # We may want to add is_upcoming, and post_live to this check but I have not been able to test it.
        if self.data.get("live_status", "") == "is_live":
            return True

        # Warning: questionable methods from here on.
        if self.extractor.startswith("generic"):
            # check against known streaming service headers.
            if self.http_header("ICY-NAME") or self.http_header("ICY-URL"):
                return True

            # hacky not good way to last ditch it.
            # url = self.url.lower()
            # if "live" in url or "stream" in url:
            #    return True

        return False
import asyncio
import datetime
import logging
import os
import re
import shutil
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Union

import discord
from yt_dlp.utils import (  # type: ignore[import-untyped]
    ContentTooShortError,
    YoutubeDLError,
)

from .constructs import Serializable
from .downloader import YtdlpResponseDict
from .exceptions import ExtractionError, InvalidDataError, MusicbotException
from .i18n import _X
from .spotify import Spotify

if TYPE_CHECKING:
    from .downloader import Downloader
    from .filecache import AudioFileCache
    from .playlist import Playlist

    # Explicit compat with python 3.8
    AsyncFuture = asyncio.Future[Any]
    AsyncTask = asyncio.Task[Any]
else:
    AsyncFuture = asyncio.Future
    AsyncTask = asyncio.Task

GuildMessageableChannels = Union[
    discord.Thread,
    discord.TextChannel,
    discord.VoiceChannel,
    discord.StageChannel,
]

log = logging.getLogger(__name__)

# optionally using pymediainfo instead of ffprobe if presents
try:
    import pymediainfo  # type: ignore[import-untyped]
except ImportError:
    log.debug("module 'pymediainfo' not found, will fall back to ffprobe.")
    pymediainfo = None


class BasePlaylistEntry(Serializable):
    def __init__(self) -> None:
        """
        Manage a playable media reference and its meta data.
        Either a URL or a local file path that ffmpeg can use.
        """
        self.filename: str = ""
        self.downloaded_bytes: int = 0
        self.cache_busted: bool = False
        self._is_downloading: bool = False
        self._is_downloaded: bool = False
        self._waiting_futures: List[AsyncFuture] = []
        self._task_pool: Set[AsyncTask] = set()

    @property
    def start_time(self) -> float:
        """
        Time in seconds that is passed to ffmpeg -ss flag.
        """
        return 0

    @property
    def url(self) -> str:
        """
        Get a URL suitable for YoutubeDL to download, or likewise
        suitable for ffmpeg to stream or directly play back.
        """
        raise NotImplementedError

    @property
    def title(self) -> str:
        """
        Get a title suitable for display using any extracted info.
        """
        raise NotImplementedError

    @property
    def duration_td(self) -> datetime.timedelta:
        """
        Get this entry's duration as a timedelta object.
        The object may contain a 0 value.
        """
        raise NotImplementedError

    @property
    def is_downloaded(self) -> bool:
        """
        Get the entry's downloaded status.
        Typically set by _download function.
        """
        if self._is_downloading:
            return False

        return bool(self.filename) and self._is_downloaded

    @property
    def is_downloading(self) -> bool:
        """Get the entry's downloading status. Usually False."""
        return self._is_downloading

    async def _download(self) -> None:
        """
        Take any steps needed to download the media and make it ready for playback.
        If the media already exists, this function can return early.
        """
        raise NotImplementedError

    def get_ready_future(self) -> AsyncFuture:
        """
        Returns a future that will fire when the song is ready to be played.
        The future will either fire with the result (being the entry) or an exception
        as to why the song download failed.
        """
        future: AsyncFuture = asyncio.Future()
        if self.is_downloaded:
            # In the event that we're downloaded, we're already ready for playback.
            future.set_result(self)

        else:
            # If we request a ready future, let's ensure that it'll actually resolve at one point.
            self._waiting_futures.append(future)
            task = asyncio.create_task(self._download(), name="MB_EntryReadyTask")
            # Make sure garbage collection does not delete the task early...
            self._task_pool.add(task)
            task.add_done_callback(self._task_pool.discard)

        log.debug("Created future for %r", self)
        return future

    def _for_each_future(self, cb: Callable[..., Any]) -> None:
        """
        Calls `cb` for each future that is not canceled.
        Absorbs and logs any errors that may have occurred.
        """
        futures = self._waiting_futures
        self._waiting_futures = []

        log.everything(  # type: ignore[attr-defined]
            "Completed futures for %(entry)r with %(callback)r",
            {"entry": self, "callback": cb},
        )
        for future in futures:
            if future.cancelled():
                continue

            try:
                cb(future)
            except Exception:  # pylint: disable=broad-exception-caught
                log.exception("Unhandled exception in _for_each_future callback.")

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}(url='{self.url}', title='{self.title}' file='{self.filename}')>"


async def run_command(command: List[str]) -> bytes:
    """
    Use an async subprocess exec to execute the given `command`
    This method will wait for then return the output.

    :param: command:
        Must be a list of arguments, where element 0 is an executable path.

    :returns:  stdout concatenated with stderr as bytes.
    """
    p = await asyncio.create_subprocess_exec(
        # The inconsistency between the various implements of subprocess, asyncio.subprocess, and
        # all the other process calling functions tucked into python is alone enough to be dangerous.
        # There is a time and place for everything, and this is not the time or place for shells.
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    log.noise(  # type: ignore[attr-defined]
        "Starting asyncio subprocess (%(process)s) with command: %(run)s",
        {"process": p, "run": command},
    )
    stdout, stderr = await p.communicate()
    return stdout + stderr


class URLPlaylistEntry(BasePlaylistEntry):
    SERIAL_VERSION: int = 3  # version for serial data checks.

    def __init__(
        self,
        playlist: "Playlist",
        info: YtdlpResponseDict,
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
    ) -> None:
        """
        Create URL Playlist entry that will be downloaded for playback.

        :param: playlist:  The playlist object this entry should belong to.
        :param: info:  A YtdlResponseDict from downloader.extract_info()
        """
        super().__init__()

        self._start_time: Optional[float] = None
        self._playback_rate: Optional[float] = None
        self.playlist: Playlist = playlist
        self.downloader: Downloader = playlist.bot.downloader
        self.filecache: AudioFileCache = playlist.bot.filecache

        self.info: YtdlpResponseDict = info

        if self.duration is None:
            log.info(
                "Extraction did not provide a duration for this entry.\n"
                "MusicBot cannot estimate queue times until it is downloaded.\n"
                "Entry name:  %s",
                self.title,
            )

        self.author: Optional[discord.Member] = author
        self.channel: Optional[GuildMessageableChannels] = channel

        self._aopt_eq: str = ""

    @property
    def aoptions(self) -> str:
        """After input options for ffmpeg to use with this entry."""
        aopts = f"{self._aopt_eq}"
        # Set playback speed options if needed.
        if self._playback_rate is not None or self.playback_speed != 1.0:
            # Append to the EQ options if they are set.
            if self._aopt_eq:
                aopts = f"{self._aopt_eq},atempo={self.playback_speed:.3f}"
            else:
                aopts = f"-af atempo={self.playback_speed:.3f}"

        if aopts:
            return aopts

        return ""

    @property
    def boptions(self) -> str:
        """Before input options for ffmpeg to use with this entry."""
        if self._start_time is not None:
            return f"-ss {self._start_time}"
        return ""

    @property
    def from_auto_playlist(self) -> bool:
        """Returns true if the entry has an author or a channel."""
        if self.author is not None or self.channel is not None:
            return False
        return True

    @property
    def url(self) -> str:
        """Gets a playable URL from this entries info."""
        return self.info.get_playable_url()

    @property
    def title(self) -> str:
        """Gets a title string from entry info or 'Unknown'"""
        # TRANSLATORS: Placeholder for empty track title.
        return self.info.title or _X("Unknown")

    @property
    def duration(self) -> Optional[float]:
        """Gets available duration data or None"""
        # duration can be 0, if so we make sure it returns None instead.
        return self.info.get("duration", None) or None

    @duration.setter
    def duration(self, value: float) -> None:
        self.info["duration"] = value

    @property
    def duration_td(self) -> datetime.timedelta:
        """
        Returns duration as a datetime.timedelta object.
        May contain 0 seconds duration.
        """
        t = self.duration or 0
        return datetime.timedelta(seconds=t)

    @property
    def thumbnail_url(self) -> str:
        """Get available thumbnail from info or an empty string"""
        return self.info.thumbnail_url

    @property
    def expected_filename(self) -> Optional[str]:
        """Get the expected filename from info if available or None"""
        return self.info.get("__expected_filename", None)

    def __json__(self) -> Dict[str, Any]:
        """
        Handles representing this object as JSON.
        """
        # WARNING:  if you change data or keys here, you must increase SERIAL_VERSION.
        return self._enclose_json(
            {
                "version": URLPlaylistEntry.SERIAL_VERSION,
                "info": self.info.data,
                "downloaded": self.is_downloaded,
                "filename": self.filename,
                "author_id": self.author.id if self.author else None,
                "channel_id": self.channel.id if self.channel else None,
                "aoptions": self.aoptions,
            }
        )

    @classmethod
    def _deserialize(
        cls,
        raw_json: Dict[str, Any],
        playlist: Optional["Playlist"] = None,
        **kwargs: Dict[str, Any],
    ) -> Optional["URLPlaylistEntry"]:
        """
        Handles converting from JSON to URLPlaylistEntry.
        """
        # WARNING:  if you change data or keys here, you must increase SERIAL_VERSION.

        # yes this is an Optional that is, in fact, not Optional. :)
        assert playlist is not None, cls._bad("playlist")

        vernum: Optional[int] = raw_json.get("version", None)
        if not vernum:
            log.error("Entry data is missing version number, cannot deserialize.")
            return None
        if vernum != URLPlaylistEntry.SERIAL_VERSION:
            log.error("Entry data has the wrong version number, cannot deserialize.")
            return None

        try:
            info = YtdlpResponseDict(raw_json["info"])
            downloaded = (
                raw_json["downloaded"] if playlist.bot.config.save_videos else False
            )
            filename = raw_json["filename"] if downloaded else ""

            channel_id = raw_json.get("channel_id", None)
            if channel_id:
                o_channel = playlist.bot.get_channel(int(channel_id))

                if not o_channel:
                    log.warning(
                        "Deserialized URLPlaylistEntry cannot find channel with ID:  %s",
                        raw_json["channel_id"],
                    )

                if isinstance(
                    o_channel,
                    (
                        discord.Thread,
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                    ),
                ):
                    channel = o_channel
                else:
                    log.warning(
                        "Deserialized URLPlaylistEntry has the wrong channel type:  %s",
                        type(o_channel),
                    )
                    channel = None
            else:
                channel = None

            author_id = raw_json.get("author_id", None)
            if author_id:
                if isinstance(
                    channel,
                    (
                        discord.Thread,
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                    ),
                ):
                    author = channel.guild.get_member(int(author_id))

                    if not author:
                        log.warning(
                            "Deserialized URLPlaylistEntry cannot find author with ID:  %s",
                            raw_json["author_id"],
                        )
                else:
                    author = None
                    log.warning(
                        "Deserialized URLPlaylistEntry has an author ID but no channel for lookup!",
                    )
            else:
                author = None

            entry = cls(playlist, info, author=author, channel=channel)
            entry.filename = filename

            return entry
        except (ValueError, TypeError, KeyError) as e:
            log.error("Could not load %s", cls.__name__, exc_info=e)

        return None

    @property
    def start_time(self) -> float:
        if self._start_time is not None:
            return self._start_time
        return 0

    def set_start_time(self, start_time: float) -> None:
        """Sets a start time in seconds to use with the ffmpeg -ss flag."""
        self._start_time = start_time

    @property
    def playback_speed(self) -> float:
        """Get the current playback speed if one was set, or return 1.0 for normal playback."""
        if self._playback_rate is not None:
            return self._playback_rate
        return self.playlist.bot.config.default_speed or 1.0

    def set_playback_speed(self, speed: float) -> None:
        """Set the playback speed to be used with ffmpeg -af:atempo filter."""
        self._playback_rate = speed

    async def _ensure_entry_info(self) -> None:
        """helper to ensure this entry object has critical information"""

        # handle some extra extraction here so we can allow spotify links in the queue.
        if "open.spotify.com" in self.url.lower() and Spotify.is_url_supported(
            self.url
        ):
            info = await self.downloader.extract_info(self.url, download=False)
            if info.ytdl_type == "url":
                self.info = info
            else:
                raise InvalidDataError(
                    "Cannot download Spotify links, processing error with type: %(type)s",
                    fmt_args={"type": info.ytdl_type},
                )

        # if this isn't set this entry is probably from a playlist and needs more info.
        if not self.expected_filename:
            new_info = await self.downloader.extract_info(self.url, download=False)
            self.info.data = {**self.info.data, **new_info.data}

    async def _download(self) -> None:
        if self._is_downloading:
            return
        log.debug("Getting ready for entry:  %r", self)

        self._is_downloading = True
        try:
            # Ensure any late-extraction links, like Spotify tracks, get processed.
            await self._ensure_entry_info()

            # Ensure the folder that we're going to move into exists.
            self.filecache.ensure_cache_dir_exists()

            # check and see if the expected file already exists in cache.
            if self.expected_filename:
                # get an existing cache path if we have one.
                file_cache_path = self.filecache.get_if_cached(self.expected_filename)

                # win a cookie if cache worked but extension was different.
                if file_cache_path and self.expected_filename != file_cache_path:
                    log.warning("Download cached with different extension...")

                # check if cache size matches remote, basic validation.
                if file_cache_path:
                    local_size = os.path.getsize(file_cache_path)
                    remote_size = int(self.info.http_header("CONTENT-LENGTH", 0))

                    if local_size != remote_size:
                        log.debug(
                            "Local size different from remote size. Re-downloading..."
                        )
                        await self._really_download()
                    else:
                        log.debug("Download already cached at:  %s", file_cache_path)
                        self.filename = file_cache_path
                        self._is_downloaded = True

                # nothing cached, time to download for real.
                else:
                    await self._really_download()

            # check for duration and attempt to extract it if missing.
            if self.duration is None:
                # optional pymediainfo over ffprobe?
                if pymediainfo:
                    self.duration = self._get_duration_pymedia(self.filename)

                # no matter what, ffprobe should be available.
                if self.duration is None:
                    self.duration = await self._get_duration_ffprobe(self.filename)

                if not self.duration:
                    log.error(
                        "MusicBot could not get duration data for this entry.\n"
                        "Queue time estimation may be unavailable until this track is cleared.\n"
                        "Entry file: %s",
                        self.filename,
                    )
                else:
                    log.debug(
                        "Got duration of %(time)s seconds for file:  %(file)s",
                        {"time": self.duration, "file": self.filename},
                    )

            if self.playlist.bot.config.use_experimental_equalization:
                try:
                    self._aopt_eq = await self.get_mean_volume(self.filename)

                # Unfortunate evil that we abide for now...
                except Exception:  # pylint: disable=broad-exception-caught
                    log.error(
                        "There as a problem with working out EQ, likely caused by a strange installation of FFmpeg. "
                        "This has not impacted the ability for the bot to work, but will mean your tracks will not be equalized.",
                        exc_info=True,
                    )

            # Trigger ready callbacks.
            self._for_each_future(lambda future: future.set_result(self))

        # Flake8 thinks 'e' is never used, and later undefined. Maybe the lambda is too much.
        except Exception as e:  # pylint: disable=broad-exception-caught
            ex = e
            if log.getEffectiveLevel() <= logging.DEBUG:
                log.error("Exception while checking entry data.")
            self._for_each_future(lambda future: future.set_exception(ex))

        finally:
            self._is_downloading = False

    def _get_duration_pymedia(self, input_file: str) -> Optional[float]:
        """
        Tries to use pymediainfo module to extract duration, if the module is available.
        """
        if pymediainfo:
            log.debug("Trying to get duration via pymediainfo for:  %s", input_file)
            try:
                mediainfo = pymediainfo.MediaInfo.parse(input_file)
                if mediainfo.tracks:
                    return int(mediainfo.tracks[0].duration) / 1000
            except (FileNotFoundError, OSError, RuntimeError, ValueError, TypeError):
                log.exception("Failed to get duration via pymediainfo.")
        return None

    async def _get_duration_ffprobe(self, input_file: str) -> Optional[float]:
        """
        Tries to use ffprobe to extract duration from media if possible.
        """
        log.debug("Trying to get duration via ffprobe for:  %s", input_file)
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            log.error("Could not locate ffprobe in your path!")
            return None

        ffprobe_cmd = [
            ffprobe_bin,
            "-i",
            self.filename,
            "-show_entries",
            "format=duration",
            "-v",
            "quiet",
            "-of",
            "csv=p=0",
        ]

        try:
            raw_output = await run_command(ffprobe_cmd)
            output = raw_output.decode("utf8")
            return float(output)
        except (ValueError, UnicodeError):
            log.error(
                "ffprobe returned something that could not be used.", exc_info=True
            )
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("ffprobe could not be executed for some reason.")

        return None

    async def get_mean_volume(self, input_file: str) -> str:
        """
        Attempt to calculate the mean volume of the `input_file` by using
        output from ffmpeg to provide values which can be used by command
        arguments sent to ffmpeg during playback.
        """
        log.debug("Calculating mean volume of:  %s", input_file)
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            log.error("Could not locate ffmpeg on your path!")
            return ""

        # NOTE: this command should contain JSON, but I have no idea how to make
        # ffmpeg spit out only the JSON.
        ffmpeg_cmd = [
            ffmpeg_bin,
            "-i",
            input_file,
            "-af",
            "loudnorm=I=-24.0:LRA=7.0:TP=-2.0:linear=true:print_format=json",
            "-f",
            "null",
            "/dev/null",
            "-hide_banner",
            "-nostats",
        ]

        raw_output = await run_command(ffmpeg_cmd)
        output = raw_output.decode("utf-8")

        i_matches = re.findall(r'"input_i" : "(-?([0-9]*\.[0-9]+))",', output)
        if i_matches:
            # log.debug("i_matches=%s", i_matches[0][0])
            i_value = float(i_matches[0][0])
        else:
            log.debug("Could not parse 'I' in normalize json.")
            i_value = float(0)

        lra_matches = re.findall(r'"input_lra" : "(-?([0-9]*\.[0-9]+))",', output)
        if lra_matches:
            # log.debug("lra_matches=%s", lra_matches[0][0])
            lra_value = float(lra_matches[0][0])
        else:
            log.debug("Could not parse 'LRA' in normalize json.")
            lra_value = float(0)

        tp_matches = re.findall(r'"input_tp" : "(-?([0-9]*\.[0-9]+))",', output)
        if tp_matches:
            # log.debug("tp_matches=%s", tp_matches[0][0])
            tp_value = float(tp_matches[0][0])
        else:
            log.debug("Could not parse 'TP' in normalize json.")
            tp_value = float(0)

        thresh_matches = re.findall(r'"input_thresh" : "(-?([0-9]*\.[0-9]+))",', output)
        if thresh_matches:
            # log.debug("thresh_matches=%s", thresh_matches[0][0])
            thresh = float(thresh_matches[0][0])
        else:
            log.debug("Could not parse 'thresh' in normalize json.")
            thresh = float(0)

        offset_matches = re.findall(r'"target_offset" : "(-?([0-9]*\.[0-9]+))', output)
        if offset_matches:
            # log.debug("offset_matches=%s", offset_matches[0][0])
            offset = float(offset_matches[0][0])
        else:
            log.debug("Could not parse 'offset' in normalize json.")
            offset = float(0)

        loudnorm_opts = (
            "-af loudnorm=I=-24.0:LRA=7.0:TP=-2.0:linear=true:"
            f"measured_I={i_value}:"
            f"measured_LRA={lra_value}:"
            f"measured_TP={tp_value}:"
            f"measured_thresh={thresh}:"
            f"offset={offset}"
        )
        return loudnorm_opts

    async def _really_download(self) -> None:
        """
        Actually download the media in this entry into cache.
        """
        log.info("Download started:  %r", self)

        info = None
        for attempt in range(1, 4):
            log.everything(  # type: ignore[attr-defined]
                "Download attempt %s of 3...", attempt
            )
            try:
                info = await self.downloader.extract_info(self.url, download=True)
                break
            except ContentTooShortError as e:
                # this typically means connection was interrupted, any
                # download is probably partial. we should definitely do
                # something about it to prevent broken cached files.
                if attempt < 3:
                    wait_for = 1.5 * attempt
                    log.warning(
                        "Download incomplete, retrying in %(time).1f seconds.  Reason: %(raw_error)s",
                        {"time": wait_for, "raw_error": e},
                    )
                    await asyncio.sleep(wait_for)  # TODO: backoff timer maybe?
                    continue

                # Mark the file I guess, and maintain the default of raising ExtractionError.
                log.error(
                    "Download failed, not retrying! Reason:  %(raw_error)s",
                    {"raw_error": e},
                )
                self.cache_busted = True
                raise ExtractionError(
                    "Download did not complete due to an error: %(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e
            except YoutubeDLError as e:
                # as a base exception for any exceptions raised by yt_dlp.
                raise ExtractionError(
                    "Download failed due to a yt-dlp error: %(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

            except Exception as e:
                log.error(
                    "Extraction encountered an unhandled exception.",
                    exc_info=self.playlist.bot.config.debug_mode,
                )
                raise MusicbotException(
                    "Download failed due to an unhandled exception: %(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e

        if info is None:
            log.error("Download failed:  %r", self)
            raise ExtractionError("Failed to extract data for the requested media.")

        log.info("Download complete:  %r", self)

        self._is_downloaded = True
        self.filename = info.expected_filename or ""

        # It should be safe to get our newly downloaded file size now...
        # This should also leave self.downloaded_bytes set to 0 if the file is in cache already.
        self.downloaded_bytes = os.path.getsize(self.filename)


class StreamPlaylistEntry(BasePlaylistEntry):
    SERIAL_VERSION: int = 3

    def __init__(
        self,
        playlist: "Playlist",
        info: YtdlpResponseDict,
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
    ) -> None:
        """
        Create Stream Playlist entry that will be sent directly to ffmpeg for playback.

        :param: playlist:  The playlist object this entry should belong to.
        :param: info:  A YtdlResponseDict with from downloader.extract_info()
        :param: from_apl:  Flag this entry as automatic playback, not queued by a user.
        :param: meta:  a collection extra of key-values stored with the entry.
        """
        super().__init__()

        self.playlist: Playlist = playlist
        self.info: YtdlpResponseDict = info

        self.author: Optional[discord.Member] = author
        self.channel: Optional[GuildMessageableChannels] = channel

        self.filename: str = self.url

    @property
    def from_auto_playlist(self) -> bool:
        """Returns true if the entry has an author or a channel."""
        if self.author is not None or self.channel is not None:
            return False
        return True

    @property
    def url(self) -> str:
        """get extracted url if available or otherwise return the input subject"""
        if self.info.extractor and self.info.url:
            return self.info.url
        return self.info.input_subject

    @property
    def title(self) -> str:
        """Gets a title string from entry info or 'Unknown'"""
        # special case for twitch streams, from previous code.
        # TODO: test coverage here
        if self.info.extractor == "twitch:stream":
            dtitle = self.info.get("description", None)
            if dtitle and not self.info.title:
                return str(dtitle)

        return self.info.title or _X("Unknown")

    @property
    def duration(self) -> Optional[float]:
        """Gets available duration data or None"""
        # duration can be 0, if so we make sure it returns None instead.
        return self.info.get("duration", None) or None

    @duration.setter
    def duration(self, value: float) -> None:
        self.info["duration"] = value

    @property
    def duration_td(self) -> datetime.timedelta:
        """
        Get timedelta object from any known duration data.
        May contain a 0 second duration.
        """
        t = self.duration or 0
        return datetime.timedelta(seconds=t)

    @property
    def thumbnail_url(self) -> str:
        """Get available thumbnail from info or an empty string"""
        return self.info.thumbnail_url

    @property
    def playback_speed(self) -> float:
        """Playback speed for streamed entries cannot typically be adjusted."""
        return 1.0

    def __json__(self) -> Dict[str, Any]:
        return self._enclose_json(
            {
                "version": StreamPlaylistEntry.SERIAL_VERSION,
                "info": self.info.data,
                "filename": self.filename,
                "author_id": self.author.id if self.author else None,
                "channel_id": self.channel.id if self.channel else None,
            }
        )

    @classmethod
    def _deserialize(
        cls,
        raw_json: Dict[str, Any],
        playlist: Optional["Playlist"] = None,
        **kwargs: Any,
    ) -> Optional["StreamPlaylistEntry"]:
        assert playlist is not None, cls._bad("playlist")

        vernum = raw_json.get("version", None)
        if not vernum:
            log.error("Entry data is missing version number, cannot deserialize.")
            return None
        if vernum != URLPlaylistEntry.SERIAL_VERSION:
            log.error("Entry data has the wrong version number, cannot deserialize.")
            return None

        try:
            info = YtdlpResponseDict(raw_json["info"])
            filename = raw_json["filename"]

            channel_id = raw_json.get("channel_id", None)
            if channel_id:
                o_channel = playlist.bot.get_channel(int(channel_id))

                if not o_channel:
                    log.warning(
                        "Deserialized StreamPlaylistEntry cannot find channel with ID:  %s",
                        raw_json["channel_id"],
                    )

                if isinstance(
                    o_channel,
                    (
                        discord.Thread,
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                    ),
                ):
                    channel = o_channel
                else:
                    log.warning(
                        "Deserialized StreamPlaylistEntry has the wrong channel type:  %s",
                        type(o_channel),
                    )
                    channel = None
            else:
                channel = None

            author_id = raw_json.get("author_id", None)
            if author_id:
                if isinstance(
                    channel,
                    (
                        discord.Thread,
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                    ),
                ):
                    author = channel.guild.get_member(int(author_id))

                    if not author:
                        log.warning(
                            "Deserialized StreamPlaylistEntry cannot find author with ID:  %s",
                            raw_json["author_id"],
                        )
                else:
                    author = None
                    log.warning(
                        "Deserialized StreamPlaylistEntry has an author ID but no channel for lookup!",
                    )
            else:
                author = None

            entry = cls(playlist, info, author=author, channel=channel)
            entry.filename = filename
            return entry
        except (ValueError, KeyError, TypeError) as e:
            log.error("Could not load %s", cls.__name__, exc_info=e)

        return None

    async def _download(self) -> None:
        log.debug("Getting ready for entry:  %r", self)
        self._is_downloading = True
        self._is_downloaded = True
        self.filename = self.url
        self._is_downloading = False

        self._for_each_future(lambda future: future.set_result(self))


class LocalFilePlaylistEntry(BasePlaylistEntry):
    SERIAL_VERSION: int = 1

    def __init__(
        self,
        playlist: "Playlist",
        info: YtdlpResponseDict,
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
    ) -> None:
        """
        Create URL Playlist entry that will be downloaded for playback.

        :param: playlist:  The playlist object this entry should belong to.
        :param: info:  A YtdlResponseDict from downloader.extract_info()
        """
        super().__init__()

        self._start_time: Optional[float] = None
        self._playback_rate: Optional[float] = None
        self.playlist: Playlist = playlist

        self.info: YtdlpResponseDict = info
        self.filename = self.expected_filename or ""

        # TODO: maybe it is worth getting duration as early as possible...

        self.author: Optional[discord.Member] = author
        self.channel: Optional[GuildMessageableChannels] = channel

        self._aopt_eq: str = ""

    @property
    def aoptions(self) -> str:
        """After input options for ffmpeg to use with this entry."""
        aopts = f"{self._aopt_eq}"
        # Set playback speed options if needed.
        if self._playback_rate is not None or self.playback_speed != 1.0:
            # Append to the EQ options if they are set.
            if self._aopt_eq:
                aopts = f"{self._aopt_eq},atempo={self.playback_speed:.3f}"
            else:
                aopts = f"-af atempo={self.playback_speed:.3f}"

        if aopts:
            return aopts

        return ""

    @property
    def boptions(self) -> str:
        """Before input options for ffmpeg to use with this entry."""
        if self._start_time is not None:
            return f"-ss {self._start_time}"
        return ""

    @property
    def from_auto_playlist(self) -> bool:
        """Returns true if the entry has an author or a channel."""
        if self.author is not None or self.channel is not None:
            return False
        return True

    @property
    def url(self) -> str:
        """Gets a playable URL from this entries info."""
        return self.info.get_playable_url()

    @property
    def title(self) -> str:
        """Gets a title string from entry info or 'Unknown'"""
        return self.info.title or _X("Unknown")

    @property
    def duration(self) -> Optional[float]:
        """Gets available duration data or None"""
        # duration can be 0, if so we make sure it returns None instead.
        return self.info.get("duration", None) or None

    @duration.setter
    def duration(self, value: float) -> None:
        self.info["duration"] = value

    @property
    def duration_td(self) -> datetime.timedelta:
        """
        Returns duration as a datetime.timedelta object.
        May contain 0 seconds duration.
        """
        t = self.duration or 0
        return datetime.timedelta(seconds=t)

    @property
    def thumbnail_url(self) -> str:
        """Get available thumbnail from info or an empty string"""
        return self.info.thumbnail_url

    @property
    def expected_filename(self) -> Optional[str]:
        """Get the expected filename from info if available or None"""
        return self.info.get("__expected_filename", None)

    def __json__(self) -> Dict[str, Any]:
        """
        Handles representing this object as JSON.
        """
        # WARNING:  if you change data or keys here, you must increase SERIAL_VERSION.
        return self._enclose_json(
            {
                "version": LocalFilePlaylistEntry.SERIAL_VERSION,
                "info": self.info.data,
                "filename": self.filename,
                "author_id": self.author.id if self.author else None,
                "channel_id": self.channel.id if self.channel else None,
                "aoptions": self.aoptions,
            }
        )

    @classmethod
    def _deserialize(
        cls,
        raw_json: Dict[str, Any],
        playlist: Optional["Playlist"] = None,
        **kwargs: Dict[str, Any],
    ) -> Optional["LocalFilePlaylistEntry"]:
        """
        Handles converting from JSON to LocalFilePlaylistEntry.
        """
        # WARNING:  if you change data or keys here, you must increase SERIAL_VERSION.

        # yes this is an Optional that is, in fact, not Optional. :)
        assert playlist is not None, cls._bad("playlist")

        vernum: Optional[int] = raw_json.get("version", None)
        if not vernum:
            log.error("Entry data is missing version number, cannot deserialize.")
            return None
        if vernum != LocalFilePlaylistEntry.SERIAL_VERSION:
            log.error("Entry data has the wrong version number, cannot deserialize.")
            return None

        try:
            info = YtdlpResponseDict(raw_json["info"])
            downloaded = (
                raw_json["downloaded"] if playlist.bot.config.save_videos else False
            )
            filename = raw_json["filename"] if downloaded else ""

            channel_id = raw_json.get("channel_id", None)
            if channel_id:
                o_channel = playlist.bot.get_channel(int(channel_id))

                if not o_channel:
                    log.warning(
                        "Deserialized LocalFilePlaylistEntry cannot find channel with ID:  %s",
                        raw_json["channel_id"],
                    )

                if isinstance(
                    o_channel,
                    (
                        discord.Thread,
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                    ),
                ):
                    channel = o_channel
                else:
                    log.warning(
                        "Deserialized LocalFilePlaylistEntry has the wrong channel type:  %s",
                        type(o_channel),
                    )
                    channel = None
            else:
                channel = None

            author_id = raw_json.get("author_id", None)
            if author_id:
                if isinstance(
                    channel,
                    (
                        discord.Thread,
                        discord.TextChannel,
                        discord.VoiceChannel,
                        discord.StageChannel,
                    ),
                ):
                    author = channel.guild.get_member(int(author_id))

                    if not author:
                        log.warning(
                            "Deserialized LocalFilePlaylistEntry cannot find author with ID:  %s",
                            raw_json["author_id"],
                        )
                else:
                    author = None
                    log.warning(
                        "Deserialized LocalFilePlaylistEntry has an author ID but no channel for lookup!",
                    )
            else:
                author = None

            entry = cls(playlist, info, author=author, channel=channel)
            entry.filename = filename

            return entry
        except (ValueError, TypeError, KeyError) as e:
            log.error("Could not load %s", cls.__name__, exc_info=e)

        return None

    @property
    def start_time(self) -> float:
        if self._start_time is not None:
            return self._start_time
        return 0

    def set_start_time(self, start_time: float) -> None:
        """Sets a start time in seconds to use with the ffmpeg -ss flag."""
        self._start_time = start_time

    @property
    def playback_speed(self) -> float:
        """Get the current playback speed if one was set, or return 1.0 for normal playback."""
        if self._playback_rate is not None:
            return self._playback_rate
        return self.playlist.bot.config.default_speed or 1.0

    def set_playback_speed(self, speed: float) -> None:
        """Set the playback speed to be used with ffmpeg -af:atempo filter."""
        self._playback_rate = speed

    async def _download(self) -> None:
        """
        Handle readying the local media file, by extracting info like duration
        or setting up normalized audio options.
        """
        if self._is_downloading:
            return

        log.debug("Getting ready for entry:  %r", self)

        self._is_downloading = True
        try:
            # check for duration and attempt to extract it if missing.
            if self.duration is None:
                # optional pymediainfo over ffprobe?
                if pymediainfo:
                    self.duration = self._get_duration_pymedia(self.filename)

                # no matter what, ffprobe should be available.
                if self.duration is None:
                    self.duration = await self._get_duration_ffprobe(self.filename)

                if not self.duration:
                    log.error(
                        "MusicBot could not get duration data for this entry.\n"
                        "Queue time estimation may be unavailable until this track is cleared.\n"
                        "Entry file: %s",
                        self.filename,
                    )
                else:
                    log.debug(
                        "Got duration of %(seconds)s seconds for file:  %(file)s",
                        {"seconds": self.duration, "file": self.filename},
                    )

            if self.playlist.bot.config.use_experimental_equalization:
                try:
                    self._aopt_eq = await self.get_mean_volume(self.filename)

                # Unfortunate evil that we abide for now...
                except Exception:  # pylint: disable=broad-exception-caught
                    log.error(
                        "There as a problem with working out EQ, likely caused by a strange installation of FFmpeg. "
                        "This has not impacted the ability for the bot to work, but will mean your tracks will not be equalized.",
                        exc_info=True,
                    )

            # Trigger ready callbacks.
            self._is_downloaded = True
            self._for_each_future(lambda future: future.set_result(self))

        # Flake8 thinks 'e' is never used, and later undefined. Maybe the lambda is too much.
        except Exception as e:  # pylint: disable=broad-exception-caught
            ex = e
            if log.getEffectiveLevel() <= logging.DEBUG:
                log.error("Exception while checking entry data.")
            self._for_each_future(lambda future: future.set_exception(ex))

        finally:
            self._is_downloading = False

    def _get_duration_pymedia(self, input_file: str) -> Optional[float]:
        """
        Tries to use pymediainfo module to extract duration, if the module is available.
        """
        if pymediainfo:
            log.debug("Trying to get duration via pymediainfo for:  %s", input_file)
            try:
                mediainfo = pymediainfo.MediaInfo.parse(input_file)
                if mediainfo.tracks:
                    return int(mediainfo.tracks[0].duration) / 1000
            except (FileNotFoundError, OSError, RuntimeError, ValueError, TypeError):
                log.exception("Failed to get duration via pymediainfo.")
        return None

    async def _get_duration_ffprobe(self, input_file: str) -> Optional[float]:
        """
        Tries to use ffprobe to extract duration from media if possible.
        """
        log.debug("Trying to get duration via ffprobe for:  %s", input_file)
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            log.error("Could not locate ffprobe in your path!")
            return None

        ffprobe_cmd = [
            ffprobe_bin,
            "-i",
            self.filename,
            "-show_entries",
            "format=duration",
            "-v",
            "quiet",
            "-of",
            "csv=p=0",
        ]

        try:
            raw_output = await run_command(ffprobe_cmd)
            output = raw_output.decode("utf8")
            return float(output)
        except (ValueError, UnicodeError):
            log.error(
                "ffprobe returned something that could not be used.", exc_info=True
            )
        except Exception:  # pylint: disable=broad-exception-caught
            log.exception("ffprobe could not be executed for some reason.")

        return None

    async def get_mean_volume(self, input_file: str) -> str:
        """
        Attempt to calculate the mean volume of the `input_file` by using
        output from ffmpeg to provide values which can be used by command
        arguments sent to ffmpeg during playback.
        """
        log.debug("Calculating mean volume of:  %s", input_file)
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            log.error("Could not locate ffmpeg on your path!")
            return ""

        # NOTE: this command should contain JSON, but I have no idea how to make
        # ffmpeg spit out only the JSON.
        ffmpeg_cmd = [
            ffmpeg_bin,
            "-i",
            input_file,
            "-af",
            "loudnorm=I=-24.0:LRA=7.0:TP=-2.0:linear=true:print_format=json",
            "-f",
            "null",
            "/dev/null",
            "-hide_banner",
            "-nostats",
        ]

        raw_output = await run_command(ffmpeg_cmd)
        output = raw_output.decode("utf-8")

        i_matches = re.findall(r'"input_i" : "(-?([0-9]*\.[0-9]+))",', output)
        if i_matches:
            # log.debug("i_matches=%s", i_matches[0][0])
            i_value = float(i_matches[0][0])
        else:
            log.debug("Could not parse 'I' in normalize json.")
            i_value = float(0)

        lra_matches = re.findall(r'"input_lra" : "(-?([0-9]*\.[0-9]+))",', output)
        if lra_matches:
            # log.debug("lra_matches=%s", lra_matches[0][0])
            lra_value = float(lra_matches[0][0])
        else:
            log.debug("Could not parse 'LRA' in normalize json.")
            lra_value = float(0)

        tp_matches = re.findall(r'"input_tp" : "(-?([0-9]*\.[0-9]+))",', output)
        if tp_matches:
            # log.debug("tp_matches=%s", tp_matches[0][0])
            tp_value = float(tp_matches[0][0])
        else:
            log.debug("Could not parse 'TP' in normalize json.")
            tp_value = float(0)

        thresh_matches = re.findall(r'"input_thresh" : "(-?([0-9]*\.[0-9]+))",', output)
        if thresh_matches:
            # log.debug("thresh_matches=%s", thresh_matches[0][0])
            thresh = float(thresh_matches[0][0])
        else:
            log.debug("Could not parse 'thresh' in normalize json.")
            thresh = float(0)

        offset_matches = re.findall(r'"target_offset" : "(-?([0-9]*\.[0-9]+))', output)
        if offset_matches:
            # log.debug("offset_matches=%s", offset_matches[0][0])
            offset = float(offset_matches[0][0])
        else:
            log.debug("Could not parse 'offset' in normalize json.")
            offset = float(0)

        loudnorm_opts = (
            "-af loudnorm=I=-24.0:LRA=7.0:TP=-2.0:linear=true:"
            f"measured_I={i_value}:"
            f"measured_LRA={lra_value}:"
            f"measured_TP={tp_value}:"
            f"measured_thresh={thresh}:"
            f"offset={offset}"
        )
        return loudnorm_opts
from enum import Enum
from typing import Any, Dict, Optional, Union


class MusicbotException(Exception):
    """
    MusicbotException is a base exception for all exceptions raised by MusicBot.
    It allows translation of messages into log and UI contexts at display time, not before.
    Thus, all messages passed to this and child exceptions must use placeholders for
    variable message segments, and abide best practices for translated messages.

    :param: message:  The untranslated string used as the exception message.
    :param: fmt_args:  A mapping for variable substitution in messages.
    :param: delete_after:  Optional timeout period to override the short delay.
                           Used only when deletion options allow it.
    """

    def __init__(
        self,
        message: str,
        *,
        delete_after: Union[None, float, int] = None,
        fmt_args: Optional[Dict[str, Any]] = None,
    ) -> None:
        # This sets base exception args to the message.
        # So str() will produce the raw, untranslated message only.
        if fmt_args:
            super().__init__(message, fmt_args)
        else:
            super().__init__(message)

        self._message = message
        self._fmt_args = fmt_args if fmt_args is not None else {}
        self.delete_after = delete_after

    @property
    def message(self) -> str:
        """Get raw message text, this has not been translated."""
        return self._message

    @property
    def fmt_args(self) -> Dict[str, Any]:
        """Get any arguments that should be formatted into the message."""
        return self._fmt_args


# Something went wrong during the processing of a command
class CommandError(MusicbotException):
    pass


# Something went wrong during the processing of a song/ytdl stuff
class ExtractionError(MusicbotException):
    pass


# Something is wrong about data
class InvalidDataError(MusicbotException):
    pass


# The no processing entry type failed and an entry was a playlist/vice versa
class WrongEntryTypeError(ExtractionError):
    pass


# FFmpeg complained about something
class FFmpegError(MusicbotException):
    pass


# FFmpeg complained about something but we don't care
class FFmpegWarning(MusicbotException):
    pass


# Some issue retrieving something from Spotify's API or processing it.
class SpotifyError(ExtractionError):
    pass


# The user doesn't have permission to use a command
class PermissionsError(CommandError):
    pass


# Error with pretty formatting for hand-holding users through various errors
class HelpfulError(MusicbotException):
    pass


class HelpfulWarning(HelpfulError):
    pass


# simple exception used to signal that initial config load should retry.
class RetryConfigException(Exception):
    pass


# Signal codes used in RestartSignal
class RestartCode(Enum):
    RESTART_SOFT = 0
    RESTART_FULL = 1
    RESTART_UPGRADE_ALL = 2
    RESTART_UPGRADE_PIP = 3
    RESTART_UPGRADE_GIT = 4


# Base class for control signals
class Signal(Exception):
    pass


# signal to restart or reload the bot
class RestartSignal(Signal):
    def __init__(self, code: RestartCode = RestartCode.RESTART_SOFT):
        self.restart_code = code

    def get_code(self) -> int:
        """Get the int value of the code contained in this signal"""
        return self.restart_code.value

    def get_name(self) -> str:
        """Get the name of the restart code contained in this signal"""
        return self.restart_code.name


# signal to end the bot "gracefully"
class TerminateSignal(Signal):
    def __init__(self, exit_code: int = 0):
        self.exit_code: int = exit_code
import asyncio
import glob
import json
import logging
import os
import pathlib
import shutil
import time
from typing import TYPE_CHECKING, Dict, Tuple

from . import write_path
from .constants import DATA_FILE_CACHEMAP, DEFAULT_DATA_DIR
from .utils import format_size_from_bytes

if TYPE_CHECKING:
    from .bot import MusicBot
    from .config import Config
    from .entry import BasePlaylistEntry, URLPlaylistEntry

log = logging.getLogger(__name__)


class AudioFileCache:
    """
    This class provides methods to manage the audio file cache and get info about it.
    """

    def __init__(self, bot: "MusicBot") -> None:
        """
        Manage data related to the audio cache, such as its current size,
        file count, file paths, and synchronization locks.
        """
        self.bot: MusicBot = bot
        self.config: Config = bot.config
        self.cache_path: pathlib.Path = bot.config.audio_cache_path
        self.cachemap_file = write_path(DEFAULT_DATA_DIR).joinpath(DATA_FILE_CACHEMAP)

        self.size_bytes: int = 0
        self.file_count: int = 0

        # Stores filenames without extension associated to a playlist URL.
        self.auto_playlist_cachemap: Dict[str, str] = {}
        self.cachemap_file_lock: asyncio.Lock = asyncio.Lock()
        self.cachemap_defer_write: bool = False

        if self.config.auto_playlist:
            self.load_autoplay_cachemap()

    @property
    def folder(self) -> pathlib.Path:
        """Get the configured cache path as a pathlib.Path"""
        return self.cache_path

    def get_if_cached(self, filename: str, ignore_ext: bool = True) -> str:
        """
        Check for an existing cache file by the given name, and return the matched path.
        The `filename` will be reduced to its basename and joined with the current cache_path.
        If `ignore_ext` is set, the filename will be matched without its last suffix / extension.
        An exact match is preferred, but only the first of many possible matches will be returned.

        :returns: a path string or empty string if not found.
        """
        file_path = pathlib.Path(filename)
        filename = file_path.name
        cache_file_path = self.cache_path.with_name(filename)

        if ignore_ext:
            if cache_file_path.is_file():
                return str(cache_file_path)

            safe_stem = glob.escape(pathlib.Path(filename).stem)
            for item in self.cache_path.glob(f"{safe_stem}.*"):
                if item.is_file():
                    return str(item)

        elif cache_file_path.is_file():
            return str(file_path)

        return ""

    def ensure_cache_dir_exists(self) -> None:
        """Check for and create the cache directory path or raise an error"""
        if not self.cache_dir_exists():
            self.cache_path.mkdir(parents=True)

    def cache_dir_exists(self) -> bool:
        """Wrapper for self.cache.is_dir() for external use."""
        return self.cache_path.is_dir()

    def get_cache_size(self) -> Tuple[int, int]:
        """
        Returns AudioFileCache size as a two member tuple containing size_bytes and file_count.
        """
        return (self.size_bytes, self.file_count)

    def scan_audio_cache(self) -> Tuple[int, int]:
        """
        Scan the audio cache directory and return a tuple with info.
        Returns (size_in_bytes:int, number_of_files:int)
        """
        cached_bytes = 0
        cached_files = 0
        if os.path.isdir(self.cache_path):
            for cache_file in pathlib.Path(self.cache_path).iterdir():
                cached_files += 1
                cached_bytes += os.path.getsize(cache_file)
        self.size_bytes = cached_bytes
        self.file_count = cached_files

        return self.get_cache_size()

    def _delete_cache_file(self, path: pathlib.Path) -> bool:
        """
        Wrapper for pathlib unlink(missing_ok=True) while logging exceptions.
        """
        try:
            path.unlink(missing_ok=True)
            return True
        except (OSError, PermissionError, IsADirectoryError):
            log.warning("Failed to delete cache file:  %s", path, exc_info=True)
            return False

    def _delete_cache_dir(self) -> bool:
        """
        Attempts immediate removal of the cache file directory while logging errors.
        """
        try:
            shutil.rmtree(self.cache_path)
            self.size_bytes = 0
            self.file_count = 0
            log.debug("Audio cache directory has been removed.")
            return True
        except (OSError, PermissionError, NotADirectoryError):
            new_name = self.cache_path.parent.joinpath(self.cache_path.stem + "__")
            try:
                new_path = self.cache_path.rename(new_name)
            except (OSError, PermissionError, FileExistsError):
                log.debug("Audio cache directory could not be removed or renamed.")
                return False
            try:
                shutil.rmtree(new_path)
                return True
            except (OSError, PermissionError, NotADirectoryError):
                new_path.rename(self.cache_path)
                log.debug("Audio cache directory could not be removed.")
                return False

    def _process_cache_delete(self) -> bool:
        """
        Sorts cache by access or creation time and deletes any that are older than set limits.
        Will retain cached autoplaylist if enabled and files are in the cachemap.
        """
        if self.config.storage_limit_bytes == 0 and self.config.storage_limit_days == 0:
            log.debug("Audio cache has no limits set, nothing to delete.")
            return False

        if os.name == "nt":
            # On Windows, creation time (ctime) is the only reliable way to do this.
            # mtime is usually older than download time. atime is changed on multiple files by some part of the player.
            # To make this consistent everywhere, we need to store last-played times for songs on our own.
            cached_files = sorted(
                self.cache_path.iterdir(),
                key=os.path.getctime,
                reverse=True,
            )
        else:
            cached_files = sorted(
                self.cache_path.iterdir(),
                key=os.path.getatime,
                reverse=True,
            )

        max_age = time.time() - (86400 * self.config.storage_limit_days)
        cached_size = 0
        removed_count = 0
        removed_size = 0
        retained_count = 0
        retained_size = 0
        # Accumulate file sizes until a set limit is reached and purge remaining files.
        for cache_file in cached_files:
            file_size = os.path.getsize(cache_file)

            # Do not purge files from autoplaylist if retention is enabled.
            if self._check_autoplay_cachemap(cache_file):
                retained_count += 1
                retained_size += file_size
                cached_size += file_size
                continue

            # get file access/creation time.
            if os.name == "nt":
                file_time = os.path.getctime(cache_file)
            else:
                file_time = os.path.getatime(cache_file)

            # enforce size limit before time limit.
            if (
                self.config.storage_limit_bytes
                and self.config.storage_limit_bytes < cached_size
            ):
                self._delete_cache_file(cache_file)
                removed_count += 1
                removed_size += file_size
                continue

            if self.config.storage_limit_days:
                if file_time < max_age:
                    self._delete_cache_file(cache_file)
                    removed_count += 1
                    removed_size += file_size
                    continue

            cached_size += file_size

        if removed_count:
            log.debug(
                "Audio cache deleted %(number)s file(s), total of %(size)s removed.",
                {
                    "number": removed_count,
                    "size": format_size_from_bytes(removed_size),
                },
            )
        if retained_count:
            log.debug(
                "Audio cached retained %(number)s file(s) from autoplaylist, total of %(size)s retained.",
                {
                    "number": retained_count,
                    "size": format_size_from_bytes(retained_size),
                },
            )
        self.file_count = len(cached_files) - removed_count
        self.size_bytes = cached_size
        log.debug(
            "Audio cache is now %(size)s over %(number)s file(s).",
            {
                "size": format_size_from_bytes(self.size_bytes),
                "number": self.file_count,
            },
        )
        return True

    def delete_old_audiocache(self, remove_dir: bool = False) -> bool:
        """
        Handle deletion of cache data according to settings and return bool status.
        Will return False if no cache directory exists, and error prevented deletion.
        Parameter `remove_dir` is intended only to be used in bot-startup.
        """

        if not os.path.isdir(self.cache_path):
            log.debug("Audio cache directory is missing, nothing to delete.")
            return False

        if self.config.save_videos:
            return self._process_cache_delete()

        if remove_dir:
            return self._delete_cache_dir()

        return True

    def handle_new_cache_entry(self, entry: "URLPlaylistEntry") -> None:
        """
        Test given entry for cachemap inclusion and run cache limit checks.
        """
        if entry.url in self.bot.playlist_mgr.loaded_tracks:
            # ignore partial downloads
            if entry.cache_busted:
                log.noise(  # type: ignore[attr-defined]
                    "Audio cache file is from autoplaylist but marked as busted, ignoring it."
                )
            else:
                self.add_autoplay_cachemap_entry(entry)

        if self.config.save_videos:
            if self.config.storage_limit_bytes:
                # TODO: This could be improved with min/max options, preventing calls to clear on each new entry.
                self.size_bytes = self.size_bytes + entry.downloaded_bytes
                if self.size_bytes > self.config.storage_limit_bytes:
                    log.debug(
                        "Cache level requires cleanup. %s",
                        format_size_from_bytes(self.size_bytes),
                    )
                    self.delete_old_audiocache()
            elif self.config.storage_limit_days:
                # Only running time check if it is the only option enabled, cuts down on IO.
                self.delete_old_audiocache()

    def load_autoplay_cachemap(self) -> None:
        """
        Load cachemap json file if it exists and settings are enabled.
        Cachemap file path is generated in Config using the auto playlist file name.
        The cache map is a dict with filename keys for playlist url values.
        Filenames are stored without their extension due to ytdl potentially getting a different format.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            self.auto_playlist_cachemap = {}
            return

        if not self.cachemap_file.is_file():
            log.debug("Auto playlist has no cache map, moving on.")
            self.auto_playlist_cachemap = {}
            return

        with open(self.cachemap_file, "r", encoding="utf8") as fh:
            try:
                self.auto_playlist_cachemap = json.load(fh)
                log.info(
                    "Loaded auto playlist cache map with %s entries.",
                    len(self.auto_playlist_cachemap),
                )
            except json.JSONDecodeError:
                log.exception("Failed to load auto playlist cache map.")
                self.auto_playlist_cachemap = {}

    async def save_autoplay_cachemap(self) -> None:
        """
        Uses asyncio.Lock to save cachemap as a json file, if settings are enabled.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        if self.cachemap_defer_write:
            log.everything(  # type: ignore[attr-defined]
                "Cachemap defer flag is set, not yet saving to disk..."
            )
            return

        async with self.cachemap_file_lock:
            try:
                with open(self.cachemap_file, "w", encoding="utf8") as fh:
                    json.dump(self.auto_playlist_cachemap, fh)
                    log.debug(
                        "Saved auto playlist cache map with %s entries.",
                        len(self.auto_playlist_cachemap),
                    )
            except (TypeError, ValueError, RecursionError):
                log.exception("Failed to save auto playlist cache map.")

    def add_autoplay_cachemap_entry(self, entry: "BasePlaylistEntry") -> None:
        """
        Store an entry in autoplaylist cachemap, and update the cachemap file if needed.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        change_made = False
        filename = pathlib.Path(entry.filename).stem
        if filename in self.auto_playlist_cachemap:
            if self.auto_playlist_cachemap[filename] != entry.url:
                log.warning(
                    "Auto playlist cache map conflict on Key: %(file)s  Old: %(old)s  New: %(new)s",
                    {
                        "file": filename,
                        "old": self.auto_playlist_cachemap[filename],
                        "new": entry.url,
                    },
                )
                self.auto_playlist_cachemap[filename] = entry.url
                change_made = True
        else:
            self.auto_playlist_cachemap[filename] = entry.url
            change_made = True

        if change_made and not self.cachemap_defer_write:
            self.bot.create_task(
                self.save_autoplay_cachemap(), name="MB_SaveAutoPlayCachemap"
            )

    def remove_autoplay_cachemap_entry(self, entry: "BasePlaylistEntry") -> None:
        """
        Remove an entry from cachemap and update cachemap file if needed.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        filename = pathlib.Path(entry.filename).stem
        if filename in self.auto_playlist_cachemap:
            del self.auto_playlist_cachemap[filename]
            if not self.cachemap_defer_write:
                self.bot.create_task(
                    self.save_autoplay_cachemap(), name="MB_SaveAutoPlayCachemap"
                )

    def remove_autoplay_cachemap_entry_by_url(self, url: str) -> None:
        """
        Remove all entries having the given URL from cachemap and update cachemap if needed.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return

        to_remove = set()
        for map_key, map_url in self.auto_playlist_cachemap.items():
            if map_url == url:
                to_remove.add(map_key)

        for key in to_remove:
            del self.auto_playlist_cachemap[key]

        if len(to_remove) != 0 and not self.cachemap_defer_write:
            self.bot.create_task(
                self.save_autoplay_cachemap(), name="MB_SaveAutoPlayCachemap"
            )

    def _check_autoplay_cachemap(self, filename: pathlib.Path) -> bool:
        """
        Test if filename is a valid autoplaylist file still.
        Returns True if map entry URL is still in autoplaylist.
        If settings are disabled for cache retention this will also return false.
        """
        if (
            not self.config.storage_retain_autoplay
            or not self.config.auto_playlist
            or not self.config.save_videos
        ):
            return False

        if filename.stem in self.auto_playlist_cachemap:
            cached_url = self.auto_playlist_cachemap[filename.stem]
            if cached_url in self.bot.playlist_mgr.loaded_tracks:
                return True

        return False
import argparse
import builtins
import ctypes
import gettext
import locale
import logging
import os
import pathlib
import sys
from typing import TYPE_CHECKING, Any, Dict, List, NoReturn, Optional, Union

from .constants import (
    DEFAULT_I18N_DIR,
    DEFAULT_I18N_LANG,
    I18N_DISCORD_TEXT_DOMAIN,
    I18N_LOGFILE_TEXT_DOMAIN,
)

if TYPE_CHECKING:
    from .constructs import GuildSpecificData

log = logging.getLogger(__name__)

Translations = Union[gettext.GNUTranslations, gettext.NullTranslations]


def _X(msg: str) -> str:  # pylint: disable=invalid-name
    """
    Mark a string for translation in all message domains.
    Strings marked are extractable but must be translated explicitly at runtime.
    """
    return msg


def _L(msg: str) -> str:  # pylint: disable=invalid-name
    """
    Marks strings for translation as part of logs domain.
    Is a shorthand for gettext() in the log domain.
    Overloaded by I18n.install() for translations.
    """
    if builtins.__dict__["_L"]:
        return str(builtins.__dict__["_L"](msg))
    return msg


def _Ln(msg: str, plural: str, n: int) -> str:  # pylint: disable=invalid-name
    """
    Marks plurals for translation as part of logs domain.
    Is a shorthand for ngettext() in the logs domain.
    Overloaded by I18n.install() for translations.
    """
    if builtins.__dict__["_Ln"]:
        return str(builtins.__dict__["_Ln"](msg, plural, n))
    return msg


def _D(  # pylint: disable=invalid-name
    msg: str, ssd: Optional["GuildSpecificData"]
) -> str:
    """
    Marks strings for translation as part of discord domain.
    Is a shorthand for I18n.sgettext() in the discord domain.
    Overloaded by I18n.install() for translations.
    """
    if builtins.__dict__["_D"]:
        return str(builtins.__dict__["_D"](msg, ssd))
    return msg


def _Dn(  # pylint: disable=invalid-name
    msg: str, plural: str, n: int, ssd: Optional["GuildSpecificData"]
) -> str:
    """
    Marks strings for translation as part of discord domain.
    Is a shorthand for I18n.sngettext() in the discord domain.
    Overloaded by I18n.install() for translations.
    """
    if builtins.__dict__["_Dn"]:
        return str(builtins.__dict__["_Dn"](msg, plural, n, ssd))
    return msg


def _Dd(msg: str) -> str:  # pylint: disable=invalid-name
    """
    Marks strings for translation as part of discord domain.
    Translation is deferred until later in runtime.
    """
    return msg


class I18n:
    """
    This class provides a utility to set up i18n via GNU gettext with automatic
    discovery of system language options as well as optional language overrides.
    Importantly, this class allows for per-guild language selection at runtime.

    The class will return gettext.GNUTranslation objects for language files
    contained within the following directory and file structure:
      [localedir] / [lang_code] / LC_MESSAGES / [domain].mo

    All [lang_code] portions are case sensitive!

    If a file cannot be found with the desired or a default language, a warning
    will be issued and strings will simply not be translated.

    By default, I18n.install() is called by init, and will make several functions
    available in global space to enable translations.
    These enable marking translations in different domains as well as providing
    for language selection in server-specific cases.
    See I18n.install() for details on global functions.
    """

    def __init__(
        self,
        localedir: Optional[pathlib.Path] = None,
        log_lang: str = "",
        msg_lang: str = "",
        auto_install: bool = True,
    ) -> None:
        """
        Initialize the i18n system, detecting system language immediately.

        :param: `localedir` An optional base path, if omitted DEFAULT_I18N_DIR constant will be used instead.
        :param: `log_lang` An optional language selection for log text that takes preference over defaults.
        :param: `msg_lang` An optional language selection for discord text that is prefered over defaults.
        :param: `auto_install` Automaticlly add global functions for translations.
        """
        # set the path where translations are stored.
        if localedir:
            self._locale_dir: pathlib.Path = localedir
        else:
            self._locale_dir = pathlib.Path(DEFAULT_I18N_DIR)
        self._locale_dir = self._locale_dir.absolute()
        self._show_sys_lang: bool = False

        # system default lanaguage code(s) if any.
        self._sys_langs: List[str] = []
        self._log_lang: str = ""
        self._msg_lang: str = ""

        # check for command line args "--lang" etc.
        self._get_lang_args()

        # selected language for logs.
        if log_lang:
            self._log_lang = log_lang

        # selected language for discord messages.
        if msg_lang:
            self._msg_lang = msg_lang

        # lang-code map to avoid the lookup overhead.
        self._discord_langs: Dict[int, Translations] = {}

        self._get_sys_langs()

        if auto_install:
            self.install()

    @property
    def default_langs(self) -> List[str]:
        """
        A list containing only the system and default language codes.
        This will always contain at least the MusicBot default language constant.
        """
        langs = self._sys_langs.copy()
        langs.append(DEFAULT_I18N_LANG)
        return langs

    @property
    def log_langs(self) -> List[str]:
        """A list of language codes used for discord messages, ordered by preference."""
        if self._log_lang:
            langs = self.default_langs
            langs.insert(0, self._log_lang)
            return langs
        return self.default_langs

    @property
    def msg_langs(self) -> List[str]:
        """A list of language codes used for discord messages, ordered by preference."""
        if self._msg_lang:
            langs = self.default_langs
            langs.insert(0, self._msg_lang)
            return langs
        return self.default_langs

    def _get_sys_langs(self) -> None:
        """
        Checks the system environment for language codes.
        """
        if os.name == "nt":
            # Windows yet again needs cytpes here, the gettext lib does not do this for us.
            windll = ctypes.windll.kernel32  # type: ignore[attr-defined]
            lang = locale.windows_locale[windll.GetUserDefaultUILanguage()]
            if lang:
                self._sys_langs = [lang]
        else:
            # check for language environment variables, but only use the first one.
            for envar in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
                val = os.environ.get(envar)
                if val:
                    self._sys_langs = val.split(":")
                    break
        if self._show_sys_lang:
            print(f"System language code(s):  {self._sys_langs}")

    def _get_lang_args(self) -> None:
        """
        Creates a stand alone, mostly silent, ArgumentParser to find command line
        args related to i18n as early as possible.
        """
        args39plus: Dict[str, Any] = {}
        if sys.version_info >= (3, 9):
            args39plus = {"exit_on_error": False}

        ap = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            usage="",
            description="",
            epilog="",
            allow_abbrev=False,
            add_help=False,
            **args39plus,
        )

        # Make sure argparser does not exit or print.
        def _error(message: str) -> NoReturn:  # type: ignore[misc]
            log.debug("Lang Argument Error:  %s", message)

        ap.error = _error  # type: ignore[method-assign]

        ap.add_argument(
            "--log_lang",
            dest="lang_logs",
            type=str,
            help="",
            default=DEFAULT_I18N_LANG,
        )
        ap.add_argument(
            "--msg_lang",
            dest="lang_msgs",
            type=str,
            help="",
            default=DEFAULT_I18N_LANG,
        )
        ap.add_argument(
            "--lang",
            dest="lang_both",
            type=str,
            help="",
            default=DEFAULT_I18N_LANG,
        )
        ap.add_argument(
            "--show_sys_lang",
            dest="show_sys_lang",
            action="store_true",
            help="",
        )

        # parse the lang args.
        args, _ = ap.parse_known_args()
        if args.show_sys_lang:
            self._show_sys_lang = True
        if args.lang_both and args.lang_both != DEFAULT_I18N_LANG:
            self._log_lang = args.lang_both
            self._msg_lang = args.lang_both
            # print(f"Lang Both:  {args.lang_both}")
        if args.lang_logs and args.lang_logs != DEFAULT_I18N_LANG:
            self._log_lang = args.lang_logs
            # print(f"Lang Logs:  {args.lang_logs}")
        if args.lang_msgs and args.lang_msgs != DEFAULT_I18N_LANG:
            self._msg_lang = args.lang_msgs
            # print(f"Lang Msgs:  {args.lang_msgs}")

    def get_log_translations(self) -> Translations:
        """
        Attempts to fetch and return a translation object for one of the languages
        contained within `I18n.log_langs` list.
        """
        t = gettext.translation(
            I18N_LOGFILE_TEXT_DOMAIN,
            localedir=self._locale_dir,
            languages=self.log_langs,
            fallback=True,
        )

        if not isinstance(t, gettext.GNUTranslations):
            log.warning(
                "Failed to load log translations for any of:  [%s]  in:  %s",
                ", ".join(self.log_langs),
                self._locale_dir,
            )

        # print(f"Logs using lanaguage: {t.info()['language']}")

        return t

    def get_discord_translation(
        self, ssd: Optional["GuildSpecificData"]
    ) -> Translations:
        """
        Get a translation object for the given `lang` in the discord message domain.
        If the language is not available a fallback from msg_langs will be used.
        """
        # Guild 0 is a fall-back used by non-guild messages.
        guild_id = 0
        if ssd:
            guild_id = ssd.guild_id

        # return mapped translations, to avoid lookups.
        if guild_id in self._discord_langs:
            tl = self._discord_langs[guild_id]
            lang_loaded = tl.info().get("language", "")
            if ssd and lang_loaded == ssd.lang_code:
                return tl
            if not guild_id:
                return tl

        # add selected lang as first option.
        msg_langs = list(self.msg_langs)
        if ssd and ssd.lang_code:
            msg_langs.insert(0, ssd.lang_code)

        # get the translations object.
        tl = gettext.translation(
            I18N_DISCORD_TEXT_DOMAIN,
            localedir=self._locale_dir,
            languages=msg_langs,
            fallback=True,
        )
        # add object to the mapping.
        self._discord_langs[guild_id] = tl

        # warn for missing translations.
        if not isinstance(tl, gettext.GNUTranslations):
            log.warning(
                "Failed to load discord translations for any of:  [%s]  guild:  %s  in:  %s",
                ", ".join(msg_langs),
                guild_id,
                self._locale_dir,
            )

        return tl

    def reset_guild_language(self, guild_id: int) -> None:
        """
        Clear the translation object mapping for the given guild ID.
        """
        if guild_id in self._discord_langs:
            del self._discord_langs[guild_id]

    def sgettext(self, msg: str, ssd: Optional["GuildSpecificData"]) -> str:
        """
        Fetch the translation object using server specific data and provide
        gettext() call for the guild's language.
        """
        t = self.get_discord_translation(ssd)
        return t.gettext(msg)

    def sngettext(
        self, signular: str, plural: str, n: int, ssd: "GuildSpecificData"
    ) -> str:
        """
        Fetch the translation object using server specific data and provide
        ngettext() call for the guild's language.
        """
        t = self.get_discord_translation(ssd)
        return t.ngettext(signular, plural, n)

    def install(self) -> None:
        """
        Registers global functions for translation domains used by MusicBot.
        It will map the following names as global functions:

         _L()  = gettext.gettext()  in log text domain.
         _Ln() = gettext.ngettext() in log text domain.
         _D()  = gettext.gettext()  in discord text domain.
         _Dn() = gettext.ngettext() in discord text domain.
        """
        log_tl = self.get_log_translations()
        builtins.__dict__["_L"] = log_tl.gettext
        builtins.__dict__["_Ln"] = log_tl.ngettext
        builtins.__dict__["_D"] = self.sgettext
        builtins.__dict__["_Dn"] = self.sngettext
import json
import logging
import pathlib
from typing import Any, Dict

log = logging.getLogger(__name__)


class Json:
    def __init__(self, json_file: pathlib.Path) -> None:
        """
        Managed JSON data, where some structure is expected.
        """
        log.debug("Loading JSON file: %s", json_file)
        self.file = json_file
        self.data = self.parse()

    def parse(self) -> Dict[str, Any]:
        """Parse the file as JSON"""
        parsed = {}
        with open(self.file, encoding="utf-8") as data:
            try:
                parsed = json.load(data)
                if not isinstance(parsed, dict):
                    raise TypeError("Parsed information must be of type Dict[str, Any]")
            except (json.JSONDecodeError, TypeError):
                log.error("Error parsing %s as JSON", self.file, exc_info=True)
                parsed = {}
        return parsed

    def get(self, item: str, fallback: Any = None) -> Any:
        """Gets an item from a JSON file"""
        try:
            data = self.data[item]
        except KeyError:
            log.warning("Could not grab data from JSON key: %s", item)
            data = fallback
        return data
import datetime
import glob
import logging
import os
import sys
from typing import TYPE_CHECKING, Any

from . import write_path

# protected imports to keep run.py from breaking on missing packages.
try:
    import colorlog

    COLORLOG_LOADED = True
except ImportError:
    COLORLOG_LOADED = False

from .constants import (
    DEFAULT_DISCORD_LOG_FILE,
    DEFAULT_LOGS_KEPT,
    DEFAULT_LOGS_ROTATE_FORMAT,
    DEFAULT_MUSICBOT_LOG_FILE,
)
from .i18n import I18n

# make mypy aware of the type for the dynamic base class.
if TYPE_CHECKING:
    BaseLoggerClass = logging.Logger
else:
    BaseLoggerClass = logging.getLoggerClass()

# Log levels supported by our logger.
CRITICAL = 50
ERROR = 40
WARNING = 30
INFO = 20
DEBUG = 10
# Custom Levels
VOICEDEBUG = 6
FFMPEG = 5
NOISY = 4
EVERYTHING = 1
# End Custom Levels
NOTSET = 0

log_i18n = I18n(auto_install=False).get_log_translations()


class MusicBotLogger(BaseLoggerClass):
    def __init__(self, name: str, level: int = NOTSET) -> None:
        self.i18n = log_i18n
        super().__init__(name, level)

    # TODO: at some point we'll need to handle plurals.
    # maybe add special kwargs "plural" and "n" to select that.
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Log debug level message, translating the message first."""
        if self.isEnabledFor(DEBUG):
            msg = self.i18n.gettext(msg)
            kwargs.setdefault("stacklevel", 2)
            super().debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Log info level messge, translating the message first."""
        if self.isEnabledFor(INFO):
            msg = self.i18n.gettext(msg)
            kwargs.setdefault("stacklevel", 2)
            super().info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Log warning level message, with translation first."""
        if self.isEnabledFor(WARNING):
            msg = self.i18n.gettext(msg)
            kwargs.setdefault("stacklevel", 2)
            super().warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Log error level message, with translation first."""
        if self.isEnabledFor(ERROR):
            msg = self.i18n.gettext(msg)
            kwargs.setdefault("stacklevel", 2)
            super().error(msg, *args, **kwargs)

    def exception(  # type: ignore[override]
        self, msg: str, *args: Any, exc_info: bool = True, **kwargs: Any
    ) -> None:
        """
        Log error with exception info.
        Exception text may not be translated.
        """
        kwargs.setdefault("stacklevel", 3)
        self.error(msg, *args, exc_info=exc_info, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        """Log critical level message, with translation first."""
        if self.isEnabledFor(CRITICAL):
            msg = self.i18n.gettext(msg)
            kwargs.setdefault("stacklevel", 2)
            super().critical(msg, *args, **kwargs)

    # Custom log levels defined here.
    def voicedebug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log voicedebug level message, with translation first."""
        if self.isEnabledFor(VOICEDEBUG):
            msg = self.i18n.gettext(msg)
            self._log(VOICEDEBUG, msg, args, **kwargs)

    def ffmpeg(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log ffmpeg level message, with translation first."""
        if self.isEnabledFor(FFMPEG):
            msg = self.i18n.gettext(msg)
            self._log(FFMPEG, msg, args, **kwargs)

    def noise(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log noisy level message, with translation first."""
        if self.isEnabledFor(NOISY):
            msg = self.i18n.gettext(msg)
            self._log(NOISY, msg, args, **kwargs)

    def everything(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an everything level message, with translation first."""
        if self.isEnabledFor(EVERYTHING):
            msg = self.i18n.gettext(msg)
            self._log(EVERYTHING, msg, args, **kwargs)


def setup_loggers() -> None:
    """set up all logging handlers for musicbot and discord.py"""
    if len(logging.getLogger("musicbot").handlers) > 1:
        log = logging.getLogger("musicbot")
        log.debug("Skipping logger setup, already set up")
        return

    # Do some pre-flight checking...
    log_file = write_path(DEFAULT_MUSICBOT_LOG_FILE)
    if not log_file.parent.is_dir():
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"Cannot create log file directory due to an error:\n{str(e)}"
            ) from e

    if not log_file.is_file():
        try:
            log_file.touch(exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"Cannot create log file due to an error:\n{str(e)}"
            ) from e

    # logging checks done, we should be able to take off.
    install_logger()

    logger = logging.getLogger("musicbot")
    # initially set logging to everything, it will be changed when config is loaded.
    logger.setLevel(logging.EVERYTHING)  # type: ignore[attr-defined]

    # Setup logging to file for musicbot.
    try:
        # We could use a RotatingFileHandler or TimedRotatingFileHandler
        # however, these require more options than we currently consider
        # such as file size or fixed rotation time.
        # For now, out local implementation should be fine...
        fhandler = logging.FileHandler(
            filename=log_file,
            encoding="utf-8",
            mode="w",
            delay=True,
        )
    except Exception as e:
        raise RuntimeError(
            f"Could not create or use the log file due to an error:\n{str(e)}"
        ) from e

    fhandler.setFormatter(
        logging.Formatter(
            "[{asctime}] {levelname} - {name} | "
            "In {filename}::{threadName}({thread}), line {lineno} in {funcName}: {message}",
            style="{",
        )
    )
    logger.addHandler(fhandler)

    # Setup logging to console for musicbot, handle missing colorlog gracefully.
    shandler = logging.StreamHandler(stream=sys.stdout)
    if COLORLOG_LOADED:
        sformatter = colorlog.LevelFormatter(
            fmt={
                # Organized by level number in descending order.
                "CRITICAL": "{log_color}[{levelname}:{module}] {message}",
                "ERROR": "{log_color}[{levelname}:{module}] {message}",
                "WARNING": "{log_color}{levelname}: {message}",
                "INFO": "{log_color}{message}",
                "DEBUG": "{log_color}[{levelname}:{module}] {message}",
                "VOICEDEBUG": "{log_color}[{levelname}:{module}][{relativeCreated:.9f}] {message}",
                "FFMPEG": "{log_color}[{levelname}:{module}][{relativeCreated:.9f}] {message}",
                "NOISY": "{log_color}[{levelname}:{module}] {message}",
                "EVERYTHING": "{log_color}[{levelname}:{module}] {message}",
            },
            log_colors={
                "CRITICAL": "bold_red",
                "ERROR": "red",
                "WARNING": "yellow",
                "INFO": "white",
                "DEBUG": "cyan",
                "VOICEDEBUG": "purple",
                "FFMPEG": "bold_purple",
                "NOISY": "bold_white",
                "EVERYTHING": "bold_cyan",
            },
            style="{",
            datefmt="",
        )

    # colorlog import must have failed.
    else:
        sformatter = logging.Formatter(  # type: ignore[assignment]
            "[{name}] {levelname}: {message}",
            style="{",
        )

    shandler.setFormatter(sformatter)  # type: ignore[arg-type]
    logger.addHandler(shandler)

    # Setup logging for discord module.
    dlogger = logging.getLogger("discord")
    dhandler = logging.FileHandler(
        filename=DEFAULT_DISCORD_LOG_FILE,
        encoding="utf-8",
        mode="w",
        delay=True,
    )
    dhandler.setFormatter(
        logging.Formatter("[{asctime}] {levelname} - {name}: {message}", style="{")
    )
    dlogger.addHandler(dhandler)
    # initially set discord logging to debug, it will be changed when config is loaded.
    dlogger.setLevel(logging.DEBUG)

    # Set a flag to indicate our logs are open.
    setattr(logging, "_mb_logs_open", True)


def muffle_discord_console_log() -> None:
    """
    Changes discord console logger output to periods only.
    Kind of like a progress indicator.
    """
    dlog = logging.getLogger("discord")
    dlh = logging.StreamHandler(stream=sys.stdout)
    dlh.terminator = ""
    try:
        dlh.setFormatter(logging.Formatter("."))
    except ValueError:
        dlh.setFormatter(logging.Formatter(".", validate=False))
    dlog.addHandler(dlh)


def mute_discord_console_log() -> None:
    """
    Removes the discord console logger output handler added by muffle_discord_console_log()
    """
    dlogger = logging.getLogger("discord")
    for h in dlogger.handlers:
        if getattr(h, "terminator", None) == "":
            dlogger.removeHandler(h)
    # for console output carriage return post muffled log string.
    print()


def set_logging_level(level: int, override: bool = False) -> None:
    """
    Sets the logging level for musicbot and discord.py loggers.
    If `override` is set True, the log level will be set and future calls
    to this function must also use `override` to set a new level.
    This allows log-level to be set by CLI arguments, overriding the
    setting used in configuration file.
    """
    log = logging.getLogger("musicbot.logs")
    if hasattr(logging, "mb_level_override") and not override:
        log.debug(
            "Log level was previously set via override to: %s",
            getattr(logging, "mb_level_override"),
        )
        return

    if override:
        setattr(logging, "mb_level_override", logging.getLevelName(level))

    set_lvl_name = logging.getLevelName(level)
    log.info("Changing log level to:  %s", set_lvl_name)

    logger = logging.getLogger("musicbot")
    logger.setLevel(level)

    dlogger = logging.getLogger("discord")
    if level <= logging.DEBUG:
        dlogger.setLevel(logging.DEBUG)
    else:
        dlogger.setLevel(level)


def set_logging_max_kept_logs(number: int) -> None:
    """Inform the logger how many logs it should keep."""
    setattr(logging, "mb_max_logs_kept", number)


def set_logging_rotate_date_format(sftime: str) -> None:
    """Inform the logger how it should format rotated file date strings."""
    setattr(logging, "mb_rot_date_fmt", sftime)


def shutdown_loggers() -> None:
    """Removes all musicbot and discord log handlers"""
    if not hasattr(logging, "_mb_logs_open"):
        return

    # This is the last log line of the logger session.
    log = logging.getLogger("musicbot.logs")
    log.info("MusicBot loggers have been called to shut down.")

    setattr(logging, "_mb_logs_open", False)

    logger = logging.getLogger("musicbot")
    for handler in logger.handlers:
        handler.flush()
        handler.close()
    logger.handlers.clear()

    dlogger = logging.getLogger("discord")
    for handler in dlogger.handlers:
        handler.flush()
        handler.close()
    dlogger.handlers.clear()


def rotate_log_files(max_kept: int = -1, date_fmt: str = "") -> None:
    """
    Handles moving and pruning log files.
    By default the primary log file is always kept, and never rotated.
    If `max_kept` is set to 0, no rotation is done.
    If `max_kept` is set 1 or greater, up to this number of logs will be kept.
    This should only be used before setup_loggers() or after shutdown_loggers()

    Note: this implementation uses file glob to select then sort files based
    on their modification time.
    The glob uses the following pattern: `{stem}*.{suffix}`
    Where `stem` and `suffix` are take from the configured log file name.

    :param: max_kept:  number of old logs to keep.
    :param: date_fmt:  format compatible with datetime.strftime() for rotated filename.
    """
    if hasattr(logging, "_mb_logs_rotated"):
        print("Logs already rotated.")
        return

    # Use the input arguments or fall back to settings or defaults.
    if max_kept <= -1:
        max_kept = getattr(logging, "mb_max_logs_kept", DEFAULT_LOGS_KEPT)
        if max_kept <= -1:
            max_kept = DEFAULT_LOGS_KEPT

    if date_fmt == "":
        date_fmt = getattr(logging, "mb_rot_date_fmt", DEFAULT_LOGS_ROTATE_FORMAT)
        if date_fmt == "":
            date_fmt = DEFAULT_LOGS_ROTATE_FORMAT

    # Rotation can be disabled by setting 0.
    if not max_kept:
        print("No logs rotated.")
        return

    # Format a date that will be used for files rotated now.
    before = datetime.datetime.now().strftime(date_fmt)

    # Rotate musicbot logs
    logfile = write_path(DEFAULT_MUSICBOT_LOG_FILE)
    logpath = logfile.parent
    if logfile.is_file():
        new_name = logpath.joinpath(f"{logfile.stem}{before}{logfile.suffix}")
        # Cannot use logging here, but some notice to console is OK.
        print(
            log_i18n.gettext("Moving the log file from this run to:  %(logpath)s")
            % {"logpath": new_name}
        )
        logfile.rename(new_name)

    # Clean up old, out-of-limits, musicbot log files
    logstem = glob.escape(logfile.stem)
    logglob = sorted(
        logpath.glob(f"{logstem}*.log"),
        key=os.path.getmtime,
        reverse=True,
    )
    if len(logglob) > max_kept:
        for path in logglob[max_kept:]:
            if path.is_file():
                path.unlink()

    # Rotate discord.py logs
    dlogfile = write_path(DEFAULT_DISCORD_LOG_FILE)
    dlogpath = dlogfile.parent
    if dlogfile.is_file():
        new_name = dlogfile.parent.joinpath(f"{dlogfile.stem}{before}{dlogfile.suffix}")
        dlogfile.rename(new_name)

    # Clean up old, out-of-limits, discord log files
    logstem = glob.escape(dlogfile.stem)
    logglob = sorted(
        dlogpath.glob(f"{logstem}*.log"), key=os.path.getmtime, reverse=True
    )
    if len(logglob) > max_kept:
        for path in logglob[max_kept:]:
            if path.is_file():
                path.unlink()

    setattr(logging, "_mb_logs_rotated", True)


def install_logger() -> None:
    """Install the MusicBotLogger class for logging with translations."""
    base = logging.getLoggerClass()
    if not isinstance(base, MusicBotLogger):
        levels = {
            "VOICEDEBUG": VOICEDEBUG,
            "FFMPEG": FFMPEG,
            "NOISY": NOISY,
            "EVERYTHING": EVERYTHING,
        }
        for name, lvl in levels.items():
            setattr(logging, name, lvl)
            logging.addLevelName(lvl, name)
        logging.setLoggerClass(MusicBotLogger)
from discord import opus


def load_opus_lib() -> None:
    """
    Take steps needed to load opus library through discord.py
    """
    if opus.is_loaded():
        return

    try:
        opus._load_default()  # pylint: disable=protected-access
        return
    except OSError:
        pass

    raise RuntimeError("Could not load an opus lib.")
import configparser
import logging
import pathlib
import shutil
from typing import TYPE_CHECKING, Dict, List, Set, Tuple, Type, Union

import configupdater
import discord

from . import write_path
from .config import ConfigOption, ConfigOptionRegistry, ExtendedConfigParser, RegTypes
from .constants import (
    DEFAULT_OWNER_GROUP_NAME,
    DEFAULT_PERMS_FILE,
    DEFAULT_PERMS_GROUP_NAME,
    EXAMPLE_PERMS_FILE,
)
from .exceptions import HelpfulError, PermissionsError
from .i18n import _Dd

if TYPE_CHECKING:
    from .bot import MusicBot

log = logging.getLogger(__name__)

PERMS_ALLOW_ALL_EXTRACTOR_NAME: str = "__"


# Permissive class define the permissive value of each default permissions
class PermissionsDefaults:
    """
    Permissions system and PermissionGroup default values.
    Most values restrict access by default.
    """

    command_whitelist: Set[str] = set()
    command_blacklist: Set[str] = set()
    advanced_commandlists: bool = False
    ignore_non_voice: Set[str] = set()
    grant_to_roles: Set[int] = set()
    user_list: Set[int] = set()

    max_songs: int = 8
    max_song_length: int = 210
    max_playlist_length: int = 0
    max_search_items: int = 10

    allow_playlists: bool = True
    insta_skip: bool = False
    skip_looped: bool = False
    remove: bool = False
    skip_when_absent: bool = True
    bypass_karaoke_mode: bool = False

    summon_no_voice: bool = False

    # allow at least the extractors that the bot normally needs.
    # an empty set here allows all.
    extractors: Set[str] = {
        "generic",
        "youtube",
        "soundcloud",
        "Bandcamp",
        "spotify:musicbot",
    }

    # These defaults are not used per-group but rather for permissions system itself.
    perms_file: pathlib.Path = write_path(DEFAULT_PERMS_FILE)
    example_perms_file: pathlib.Path = write_path(EXAMPLE_PERMS_FILE)


class PermissiveDefaults(PermissionsDefaults):
    """
    The maximum allowed version of defaults.
    Most values grant access or remove limits by default.
    """

    command_whitelist: Set[str] = set()
    command_blacklist: Set[str] = set()
    advanced_commandlists: bool = False
    ignore_non_voice: Set[str] = set()
    grant_to_roles: Set[int] = set()
    user_list: Set[int] = set()

    max_songs: int = 0
    max_song_length: int = 0
    max_playlist_length: int = 0
    max_search_items: int = 10

    allow_playlists: bool = True
    insta_skip: bool = True
    skip_looped: bool = True
    remove: bool = True
    skip_when_absent: bool = False
    bypass_karaoke_mode: bool = True

    summon_no_voice: bool = True

    # an empty set here allows all.
    extractors: Set[str] = set()


class Permissions:
    def __init__(self, perms_file: pathlib.Path) -> None:
        """
        Handles locating, initializing defaults, loading, and validating
        permissions config from the given `perms_file` path.

        :param: grant_all:  a list of discord User IDs to grant permissive defaults.
        """
        self.perms_file = perms_file
        self.config = ExtendedConfigParser()
        self.register = PermissionOptionRegistry(self, self.config)
        self.groups: Dict[str, PermissionGroup] = {}

        if not self.config.read(self.perms_file, encoding="utf-8"):
            example_file = PermissionsDefaults.example_perms_file
            if example_file.is_file():
                log.warning(
                    "Permissions file not found, copying from:  %s",
                    example_file,
                )

                try:
                    shutil.copy(example_file, self.perms_file)
                    self.config.read(self.perms_file, encoding="utf-8")
                except Exception as e:
                    log.exception(
                        "Error copying example permissions file:  %s", example_file
                    )
                    raise RuntimeError(
                        f"Unable to copy {example_file} to {self.perms_file}:  {str(e)}"
                    ) from e
            else:
                log.error(
                    "Could not locate config permissions or example permissions files.\n"
                    "MusicBot will generate the config files at the location:\n"
                    "  %(perms_file)s",
                    {"perms_file": self.perms_file.parent},
                )

        for section in self.config.sections():
            if section == DEFAULT_OWNER_GROUP_NAME:
                self.groups[section] = self._generate_permissive_group(section)
            else:
                self.groups[section] = self._generate_default_group(section)

        # in case the permissions don't have a default group, make one.
        if not self.config.has_section(DEFAULT_PERMS_GROUP_NAME):
            self.groups[DEFAULT_PERMS_GROUP_NAME] = self._generate_default_group(
                DEFAULT_PERMS_GROUP_NAME
            )

        # in case the permissions don't have an owner group, create a virtual one.
        if not self.config.has_section(DEFAULT_OWNER_GROUP_NAME):
            self.groups[DEFAULT_OWNER_GROUP_NAME] = self._generate_permissive_group(
                DEFAULT_OWNER_GROUP_NAME
            )

        self.register.validate_register_destinations()

        if not self.perms_file.is_file():
            log.info("Generating new config permissions files...")
            try:
                ex_file = PermissionsDefaults.example_perms_file
                self.register.write_default_ini(ex_file)
                shutil.copy(ex_file, self.perms_file)
                self.config.read(self.perms_file, encoding="utf-8")
            except OSError as e:
                raise HelpfulError(
                    # fmt: off
                    "Error creating default config permissions file.\n"
                    "\n"
                    "Problem:\n"
                    "  MusicBot attempted to generate the config files but failed due to an error:\n"
                    "  %(raw_error)s\n"
                    "\n"
                    "Solution:\n"
                    "  Make sure MusicBot can read and write to your config files.\n",
                    # fmt: on
                    fmt_args={"raw_error": e},
                ) from e

    def _generate_default_group(self, name: str) -> "PermissionGroup":
        """Generate a group with `name` using PermissionDefaults."""
        return PermissionGroup(name, self, PermissionsDefaults)

    def _generate_permissive_group(self, name: str) -> "PermissionGroup":
        """Generate a group with `name` using PermissiveDefaults. Typically owner group."""
        return PermissionGroup(name, self, PermissiveDefaults)

    def set_owner_id(self, owner_id: int) -> None:
        """Sets the given id as the owner ID in the owner permission group."""
        if owner_id == 0:
            log.debug("Config 'OwnerID' is set auto, will set correctly later.")
        self.groups[DEFAULT_OWNER_GROUP_NAME].user_list = set([owner_id])

    @property
    def owner_group(self) -> "PermissionGroup":
        """Always returns the owner group"""
        return self.groups[DEFAULT_OWNER_GROUP_NAME]

    @property
    def default_group(self) -> "PermissionGroup":
        """Always returns the default group"""
        return self.groups[DEFAULT_PERMS_GROUP_NAME]

    async def async_validate(self, bot: "MusicBot") -> None:
        """
        Handle validation of permissions data that depends on async services.
        """
        log.debug("Validating permissions...")
        if 0 in self.owner_group.user_list:
            log.debug("Setting auto 'OwnerID' for owner permissions group.")
            self.owner_group.user_list = {bot.config.owner_id}

    def for_user(self, user: Union[discord.Member, discord.User]) -> "PermissionGroup":
        """
        Returns the first PermissionGroup a user belongs to
        :param user: A discord User or Member object
        """
        # Only ever put Owner in the Owner group.
        if user.id in self.owner_group.user_list:
            return self.owner_group

        # TODO: Maybe we should validate to prevent users in multiple groups...
        # Or complicate things more by merging groups into virtual groups......

        # Search for the first group a member ID shows up in.
        for group in self.groups.values():
            if user.id in group.user_list:
                return group

        # In case this is not a Member and has no roles, use default.
        if isinstance(user, discord.User):
            return self.default_group

        # Search groups again and associate the member by role IDs.
        for group in self.groups.values():
            for role in user.roles:
                if role.id in group.granted_to_roles:
                    return group

        # Or just assign default role.
        return self.default_group

    def add_group(self, name: str) -> None:
        """
        Creates a permission group, but does nothing to the parser.
        """
        self.groups[name] = self._generate_default_group(name)

    def remove_group(self, name: str) -> None:
        """Removes a permission group but does nothing to the parser."""
        del self.groups[name]
        self.register.unregister_group(name)

    def save_group(self, group: str) -> bool:
        """
        Converts the current Permission Group value into an INI file value as needed.
        Note: ConfigParser must not use multi-line values. This will break them.
        Should multi-line values be needed, maybe use ConfigUpdater package instead.
        """
        try:
            cu = configupdater.ConfigUpdater()
            cu.optionxform = str  # type: ignore
            cu.read(self.perms_file, encoding="utf8")

            opts = self.register.get_option_dict(group)
            # update/delete existing
            if group in set(cu.keys()):
                # update
                if group in self.groups:
                    log.debug("Updating group in permissions file:  %s", group)
                    for option in set(cu[group].keys()):
                        cu[group][option].value = self.register.to_ini(opts[option])

                # delete
                else:
                    log.debug("Deleting group from permissions file:  %s", group)
                    cu.remove_section(group)

            # add new
            elif group in self.groups:
                log.debug("Adding new group to permissions file:  %s", group)
                options = ""
                for _, opt in opts.items():
                    c_bits = opt.comment.split("\n")
                    if len(c_bits) > 1:
                        comments = "".join([f"# {x}\n" for x in c_bits])
                    else:
                        comments = f"# {opt.comment.strip()}\n"
                    ini_val = self.register.to_ini(opt)
                    options += f"{comments}{opt.option} = {ini_val}\n\n"
                new_section = configupdater.ConfigUpdater()
                new_section.optionxform = str  # type: ignore
                new_section.read_string(f"[{group}]\n{options}\n")
                cu.add_section(new_section[group].detach())

            log.debug("Saving permissions file now.")
            cu.update_file()
            return True

        # except configparser.MissingSectionHeaderError:
        except configparser.ParsingError:
            log.exception("ConfigUpdater could not parse the permissions file!")
        except configparser.DuplicateSectionError:
            log.exception("You have a duplicate section, fix your Permissions file!")
        except OSError:
            log.exception("Failed to save permissions group:  %s", group)

        return False

    def update_option(self, option: ConfigOption, value: str) -> bool:
        """
        Uses option data to parse the given value and update its associated permission.
        No data is saved to file however.
        """
        tparser = ExtendedConfigParser()
        tparser.read_dict({option.section: {option.option: value}})

        try:
            get = getattr(tparser, option.getter, None)
            if not get:
                log.critical("Dev Bug! Permission has getter that is not available.")
                return False
            new_conf_val = get(option.section, option.option, fallback=option.default)
            if not isinstance(new_conf_val, type(option.default)):
                log.error(
                    "Dev Bug! Permission has invalid type, getter and default must be the same type."
                )
                return False
            setattr(self.groups[option.section], option.dest, new_conf_val)
            return True
        except (HelpfulError, ValueError, TypeError):
            return False


class PermissionGroup:
    _BuiltIn: List[str] = [DEFAULT_PERMS_GROUP_NAME, DEFAULT_OWNER_GROUP_NAME]

    def __init__(
        self,
        name: str,
        manager: Permissions,
        defaults: Type[PermissionsDefaults],
    ) -> None:
        """
        Create a PermissionGroup object from a ConfigParser section.

        :param: name:  the name of the group
        :param: section_data:  a config SectionProxy that describes a group
        :param: fallback:  Typically a PermissionsDefaults class
        """
        self._mgr = manager

        self.name = name

        self.command_whitelist = self._mgr.register.init_option(
            section=name,
            option="CommandWhitelist",
            dest="command_whitelist",
            getter="getstrset",
            default=defaults.command_whitelist,
            comment=_Dd(
                "List of command names allowed for use, separated by spaces.\n"
                "Sub-command access can be controlled by adding _ and the sub-command name.\n"
                "That is `config_set` grants only the `set` sub-command of the config command.\n"
                "This option overrides CommandBlacklist if set.\n"
            ),
            empty_display_val="(All allowed)",
        )
        self.command_blacklist = self._mgr.register.init_option(
            section=name,
            option="CommandBlacklist",
            dest="command_blacklist",
            default=defaults.command_blacklist,
            getter="getstrset",
            comment=_Dd(
                "List of command names denied from use, separated by spaces.\n"
                "Will not work if CommandWhitelist is set!"
            ),
            empty_display_val="(None denied)",
        )
        self.advanced_commandlists = self._mgr.register.init_option(
            section=name,
            option="AdvancedCommandLists",
            dest="advanced_commandlists",
            getter="getboolean",
            default=defaults.advanced_commandlists,
            comment=_Dd(
                "When enabled, CommandBlacklist and CommandWhitelist are used together.\n"
                "Only commands in the whitelist are allowed, however sub-commands may be denied by the blacklist.\n"
            ),
        )
        self.ignore_non_voice = self._mgr.register.init_option(
            section=name,
            option="IgnoreNonVoice",
            dest="ignore_non_voice",
            getter="getstrset",
            default=defaults.ignore_non_voice,
            comment=_Dd(
                "List of command names that can only be used while in the same voice channel as MusicBot.\n"
                "Some commands will always require the user to be in voice, regardless of this list.\n"
                "Command names should be separated by spaces."
            ),
            empty_display_val="(No commands listed)",
        )
        self.granted_to_roles = self._mgr.register.init_option(
            section=name,
            option="GrantToRoles",
            dest="granted_to_roles",
            getter="getidset",
            default=defaults.grant_to_roles,
            comment=_Dd(
                "List of Discord server role IDs that are granted this permission group.\n"
                "This option is ignored if UserList is set."
            ),
            invisible=True,
        )
        self.user_list = self._mgr.register.init_option(
            section=name,
            option="UserList",
            dest="user_list",
            getter="getidset",
            default=defaults.user_list,
            comment=_Dd(
                "List of Discord member IDs that are granted permissions in this group.\n"
                "This option overrides GrantToRoles."
            ),
            invisible=True,
        )
        self.max_songs = self._mgr.register.init_option(
            section=name,
            option="MaxSongs",
            dest="max_songs",
            getter="getint",
            default=defaults.max_songs,
            comment=_Dd(
                "Maximum number of songs a user is allowed to queue.\n"
                "A value of 0 means unlimited."
            ),
            empty_display_val="(Unlimited)",
        )
        self.max_song_length = self._mgr.register.init_option(
            section=name,
            option="MaxSongLength",
            dest="max_song_length",
            getter="getint",
            default=defaults.max_song_length,
            comment=_Dd(
                "Maximum length of a song in seconds. A value of 0 means unlimited.\n"
                "This permission may not be enforced if song duration is not available."
            ),
            empty_display_val="(Unlimited)",
        )
        self.max_playlist_length = self._mgr.register.init_option(
            section=name,
            option="MaxPlaylistLength",
            dest="max_playlist_length",
            getter="getint",
            default=defaults.max_playlist_length,
            comment=_Dd(
                "Maximum number of songs a playlist is allowed to have when queued.\n"
                "A value of 0 means unlimited."
            ),
            empty_display_val="(Unlimited)",
        )
        self.max_search_items = self._mgr.register.init_option(
            section=name,
            option="MaxSearchItems",
            dest="max_search_items",
            getter="getint",
            default=defaults.max_search_items,
            comment=_Dd(
                "The maximum number of items that can be returned in a search."
            ),
        )
        self.allow_playlists = self._mgr.register.init_option(
            section=name,
            option="AllowPlaylists",
            dest="allow_playlists",
            getter="getboolean",
            default=defaults.allow_playlists,
            comment=_Dd("Allow users to queue playlists, or multiple songs at once."),
        )
        self.instaskip = self._mgr.register.init_option(
            section=name,
            option="InstaSkip",
            dest="instaskip",
            getter="getboolean",
            default=defaults.insta_skip,
            comment=_Dd(
                "Allow users to skip without voting, if LegacySkip config option is enabled."
            ),
        )
        self.skip_looped = self._mgr.register.init_option(
            section=name,
            option="SkipLooped",
            dest="skip_looped",
            getter="getboolean",
            default=defaults.skip_looped,
            comment=_Dd("Allows the user to skip a looped song."),
        )
        self.remove = self._mgr.register.init_option(
            section=name,
            option="Remove",
            dest="remove",
            getter="getboolean",
            default=defaults.remove,
            comment=_Dd(
                "Allows the user to remove any song from the queue.\n"
                "Does not remove or skip currently playing songs."
            ),
        )
        self.skip_when_absent = self._mgr.register.init_option(
            section=name,
            option="SkipWhenAbsent",
            dest="skip_when_absent",
            getter="getboolean",
            default=defaults.skip_when_absent,
            comment=_Dd(
                "Skip songs added by users who are not in voice when their song is played."
            ),
        )
        self.bypass_karaoke_mode = self._mgr.register.init_option(
            section=name,
            option="BypassKaraokeMode",
            dest="bypass_karaoke_mode",
            getter="getboolean",
            default=defaults.bypass_karaoke_mode,
            comment=_Dd(
                "Allows the user to add songs to the queue when Karaoke Mode is enabled."
            ),
        )
        self.summonplay = self._mgr.register.init_option(
            section=name,
            option="SummonNoVoice",
            dest="summonplay",
            getter="getboolean",
            default=defaults.summon_no_voice,
            comment=_Dd(
                "Auto summon to user voice channel when using play commands, if bot isn't in voice already.\n"
                "The summon command must still be allowed for this group!"
            ),
        )
        self.extractors = self._mgr.register.init_option(
            section=name,
            option="Extractors",
            dest="extractors",
            getter="getstrset",
            default=defaults.extractors,
            comment=_Dd(
                "Specify yt-dlp extractor names, separated by spaces, that are allowed to be used.\n"
                "When empty, hard-coded defaults are used. The defaults are displayed above, but may change between versions.\n"
                "To allow all extractors, add `%(allow_all)s` without quotes to the list.\n"
                "\n"
                "Services/extractors supported by yt-dlp are listed here:\n"
                "  https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md \n"
                "\n"
                "MusicBot also provides one custom service `spotify:musicbot` to enable or disable Spotify API extraction.\n"
                "NOTICE: MusicBot might not support all services available to yt-dlp!\n"
            ),
            comment_args={"allow_all": PERMS_ALLOW_ALL_EXTRACTOR_NAME},
            empty_display_val="(All allowed)",
        )

        self.validate()

    def validate(self) -> None:
        """Validate permission values are within acceptable limits"""
        if self.max_search_items > 100:
            log.warning("Max search items can't be larger than 100. Setting to 100.")
            self.max_search_items = 100

        # if extractors contains the all marker, blank out the list to allow all.
        if PERMS_ALLOW_ALL_EXTRACTOR_NAME in self.extractors:
            self.extractors = set()

        # Make sure to clear the UserList and GrantToRoles options of built-ins.
        if self.name in PermissionGroup._BuiltIn:
            self.user_list.clear()
            self.granted_to_roles.clear()

    def add_user(self, uid: int) -> None:
        """Add given discord User ID to the user list."""
        self.user_list.add(uid)

    def remove_user(self, uid: int) -> None:
        """Remove given discord User ID from the user list."""
        if uid in self.user_list:
            self.user_list.remove(uid)

    def can_use_command(self, command: str, sub: str = "") -> bool:
        """
        Test if the group can use the given command or sub-command.

        :param: command:  The command name to test.
        :param: sub:      The sub-command argument of the command being tested.

        :returns:  boolean:  False if not allowed, True otherwise.
        """
        csub = f"{command}_{sub}"
        terms = [command]
        if sub:
            terms.append(csub)

        if not self.advanced_commandlists:
            if self.command_whitelist and all(
                c not in self.command_whitelist for c in terms
            ):
                return False

            if self.command_blacklist and any(
                c in self.command_blacklist for c in terms
            ):
                return False

        else:
            if self.command_whitelist and all(
                x not in self.command_whitelist for x in terms
            ):
                return False

            if (
                sub
                and command in self.command_whitelist
                and csub in self.command_blacklist
            ):
                return False

            if any(
                c in self.command_blacklist and c in self.command_whitelist
                for c in terms
            ):
                return False
        return True

    def can_use_extractor(self, extractor: str) -> None:
        """
        Test if this group / user can use the given extractor.

        :raises:  PermissionsError  if extractor is not allowed.
        """
        # empty extractor list will allow all extractors.
        if not self.extractors:
            return

        # check the list for any partial matches.
        for allowed in self.extractors:
            if extractor.startswith(allowed):
                return

        # the extractor is not allowed.
        raise PermissionsError(
            "You do not have permission to play the requested media.\n"
            "The yt-dlp extractor `%(extractor)s` is not permitted in your group.",
            fmt_args={"extractor": extractor},
        )

    def format(self, for_user: bool = False) -> str:
        """
        Format the current group values into INI-like text.

        :param: for_user:  Present values for display, instead of literal values.
        """
        perms = f"Permission group name:  {self.name}\n"
        for opt in self._mgr.register.option_list:
            if opt.section != self.name:
                continue
            if opt.invisible and for_user:
                continue
            val = self._mgr.register.to_ini(opt)
            if not val and opt.empty_display_val:
                val = opt.empty_display_val
            perms += f"{opt.option} = {val}\n"
        return perms

    def __repr__(self) -> str:
        return f"<PermissionGroup: {self.name}>"

    def __str__(self) -> str:
        return f"<PermissionGroup: {self.name}: {self.__dict__}>"


class PermissionOptionRegistry(ConfigOptionRegistry):
    def __init__(self, config: Permissions, parser: ExtendedConfigParser) -> None:
        super().__init__(config, parser)

    def validate_register_destinations(self) -> None:
        """Check all configured options for matching destination definitions."""
        if not isinstance(self._config, Permissions):
            raise RuntimeError(
                "Dev Bug! Somehow this is Config when it should be Permissions."
            )

        errors = []
        for opt in self._option_list:
            if not hasattr(self._config.groups[opt.section], opt.dest):
                errors.append(
                    f"Permission `{opt}` has an missing destination named:  {opt.dest}"
                )
        if errors:
            msg = "Dev Bug!  Some permissions failed validation.\n"
            msg += "\n".join(errors)
            raise RuntimeError(msg)

    @property
    def distinct_options(self) -> Set[str]:
        """Unique Permission names for Permission groups."""
        return self._distinct_options

    def get_option_dict(self, group: str) -> Dict[str, ConfigOption]:
        """Get only ConfigOptions for the group, in a dict by option name."""
        return {opt.option: opt for opt in self.option_list if opt.section == group}

    def unregister_group(self, group: str) -> None:
        """Removes all registered options for group."""
        new_opts = []
        for opt in self.option_list:
            if opt.section == group:
                continue
            new_opts.append(opt)
        self._option_list = new_opts

    def get_values(self, opt: ConfigOption) -> Tuple[RegTypes, str, str]:
        """
        Get the values in PermissionGroup and *ConfigParser for this option.
        Returned tuple contains parsed value, ini-string, and a display string
        for the parsed config value if applicable.
        Display string may be empty if not used.
        """
        if not isinstance(self._config, Permissions):
            raise RuntimeError(
                "Dev Bug! Somehow this is Config when it should be Permissions."
            )

        if not opt.editable:
            return ("", "", "")

        if opt.section not in self._config.groups:
            raise ValueError(
                f"Dev Bug! PermissionGroup named `{opt.section}` does not exist."
            )

        if not hasattr(self._config.groups[opt.section], opt.dest):
            raise AttributeError(
                f"Dev Bug! Attribute `PermissionGroup.{opt.dest}` does not exist."
            )

        if not hasattr(self._parser, opt.getter):
            raise AttributeError(
                f"Dev Bug! Method `*ConfigParser.{opt.getter}` does not exist."
            )

        parser_get = getattr(self._parser, opt.getter)
        config_value = getattr(self._config.groups[opt.section], opt.dest)
        parser_value = parser_get(opt.section, opt.option, fallback=opt.default)

        display_config_value = ""
        if not config_value and opt.empty_display_val:
            display_config_value = opt.empty_display_val

        return (config_value, parser_value, display_config_value)

    def get_parser_value(self, opt: ConfigOption) -> RegTypes:
        """returns the parser's parsed value for the given option."""
        getter = getattr(self._parser, opt.getter, None)
        if getter is None:
            raise AttributeError(
                f"Dev Bug! Attribute *ConfigParser.{opt.getter} does not exist."
            )

        val: RegTypes = getter(opt.section, opt.option, fallback=opt.default)
        if not isinstance(val, type(opt.default)):
            raise TypeError("Dev Bug!  Type from parser does not match default type.")
        return val

    def to_ini(self, option: ConfigOption, use_default: bool = False) -> str:
        """
        Convert the parsed permission value into an INI value.
        This method does not perform validation, simply converts the value.

        :param: use_default:  return the default value instead of current config.
        """
        if not isinstance(self._config, Permissions):
            raise RuntimeError(
                "Dev Bug! Registry does not have Permissions config object."
            )

        if use_default:
            conf_value = option.default
        else:
            if option.section not in self._config.groups:
                raise ValueError(f"No PermissionGroup by the name `{option.section}`")

            group = self._config.groups[option.section]
            if not hasattr(group, option.dest):
                raise AttributeError(
                    f"Dev Bug! Attribute `PermissionGroup.{option.dest}` does not exist."
                )

            conf_value = getattr(group, option.dest)
        return self._value_to_ini(conf_value, option.getter)

    def write_default_ini(self, filename: pathlib.Path) -> bool:
        """Uses registry to generate an example_permissions.ini file."""
        if not isinstance(self._config, Permissions):
            raise RuntimeError("Dev bug, Permissions object expcted.")

        if DEFAULT_OWNER_GROUP_NAME not in self._config.groups:
            self._config.groups[DEFAULT_OWNER_GROUP_NAME] = (
                self._config._generate_permissive_group(  # pylint: disable=protected-access
                    DEFAULT_OWNER_GROUP_NAME
                )
            )
        if DEFAULT_PERMS_GROUP_NAME not in self._config.groups:
            self._config.add_group(DEFAULT_PERMS_GROUP_NAME)

        try:
            cu = configupdater.ConfigUpdater()
            cu.optionxform = str  # type: ignore

            # add the default sections.
            cu.add_section(DEFAULT_OWNER_GROUP_NAME)
            cu.add_section(DEFAULT_PERMS_GROUP_NAME)

            # create the comment documentation and fill in defaults for each section.
            docs = ""
            for opt in self.option_list:
                if opt.section not in [
                    DEFAULT_OWNER_GROUP_NAME,
                    DEFAULT_PERMS_GROUP_NAME,
                ]:
                    continue
                dval = self.to_ini(opt, use_default=True)
                cu[opt.section][opt.option] = dval
                if opt.section == DEFAULT_PERMS_GROUP_NAME:
                    if opt.comment_args:
                        comment = opt.comment % opt.comment_args
                    else:
                        comment = opt.comment
                    comment = "".join(
                        f"    {c}\n" for c in comment.split("\n")
                    ).rstrip()
                    docs += f" {opt.option} = {dval}\n{comment}\n\n"

            # add comments to head of file.
            adder = cu[DEFAULT_OWNER_GROUP_NAME].add_before
            head_comment = (
                "This is the permissions file for MusicBot. Do not edit this file using Notepad.\n"
                "Use Notepad++ or a code editor like Visual Studio Code.\n"
                "For help, see: https://just-some-bots.github.io/MusicBot/ \n"
                "\n"
                "This file was generated by MusicBot, it contains all options set to their default values.\n"
                "\n"
                "Basics:\n"
                "- Lines starting with semicolons (;) are comments, and are ignored.\n"
                "- Words in square brackets [ ] are permission group names.\n"
                "- Group names must be unique, and cannot be duplicated.\n"
                "- Each group must have at least one permission option defined.\n"
                "- [Default] is a reserved section. Users without a specific group assigned will use it.\n"
                "- [Owner (auto)] is a reserved section that cannot be removed, used by the Owner user.\n"
                "\nAvailable Options:\n"
                f"{docs}"
            ).strip()
            for line in head_comment.split("\n"):
                adder.comment(line, comment_prefix=";")
            adder.space()
            adder.space()

            # add owner section comment
            owner_comment = (
                "This permission group is used by the Owner only, it cannot be deleted or renamed.\n"
                "It's options only apply to Owner user set in the 'OwnerID' config option.\n"
                "You cannot set the UserList or GrantToRoles options in this group.\n"
                "This group does not control access to owner-only commands."
            )
            for line in owner_comment.split("\n"):
                adder.comment(line, comment_prefix=";")

            # add default section comment
            default_comment = (
                "This is the default permission group. It cannot be deleted or renamed.\n"
                "All users without explicit group assignment will be placed in this group.\n"
                "The options GrantToRoles and UserList are effectively ignored in this group.\n"
                "If you want to use the above options, add a new [Group] to the file."
            )
            adder = cu[DEFAULT_PERMS_GROUP_NAME].add_before
            adder.space()
            adder.space()
            for line in default_comment.split("\n"):
                adder.comment(line, comment_prefix=";")

            with open(filename, "w", encoding="utf8") as fp:
                cu.write(fp)

            return True
        except (
            configparser.DuplicateSectionError,
            configparser.ParsingError,
            OSError,
            AttributeError,
        ):
            log.exception("Failed to save default INI file at:  %s", filename)
            return False
import asyncio
import io
import json
import logging
import os
import sys
import time
from enum import Enum
from threading import Thread
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from discord import (
    AudioSource,
    FFmpegOpusAudio,
    FFmpegPCMAudio,
    PCMVolumeTransformer,
    VoiceClient,
)

from .constructs import Serializable, Serializer, SkipState
from .entry import LocalFilePlaylistEntry, StreamPlaylistEntry, URLPlaylistEntry
from .exceptions import FFmpegError, FFmpegWarning
from .lib.event_emitter import EventEmitter

if TYPE_CHECKING:
    from .bot import MusicBot
    from .playlist import Playlist

    AsyncFuture = asyncio.Future[Any]
else:
    AsyncFuture = asyncio.Future

# Type alias
EntryTypes = Union[URLPlaylistEntry, StreamPlaylistEntry, LocalFilePlaylistEntry]
FFmpegSources = Union[PCMVolumeTransformer[FFmpegPCMAudio], FFmpegOpusAudio]

log = logging.getLogger(__name__)


class MusicPlayerState(Enum):
    STOPPED = 0  # When the player isn't playing anything
    PLAYING = 1  # The player is actively playing music.
    PAUSED = 2  # The player is paused on a song.
    WAITING = (
        3  # The player has finished its song but is still downloading the next one
    )
    DEAD = 4  # The player has been killed.

    def __str__(self) -> str:
        return self.name


class SourcePlaybackCounter(AudioSource):
    def __init__(
        self,
        source: FFmpegSources,
        start_time: float = 0,
        playback_speed: float = 1.0,
    ) -> None:
        """
        Manage playback source and attempt to count progress frames used
        to measure playback progress.

        :param: start_time:  A time in seconds that was used in ffmpeg -ss flag.
        """
        # NOTE: PCMVolumeTransformer will let you set any crazy value.
        # But internally it limits between 0 and 2.0.
        self._source = source
        self._num_reads: int = 0
        self._start_time: float = start_time
        self._playback_speed: float = playback_speed
        self._is_opus_audio: bool = isinstance(source, FFmpegOpusAudio)

    def is_opus(self) -> bool:
        return self._is_opus_audio

    def read(self) -> bytes:
        res = self._source.read()
        if res:
            self._num_reads += 1
        return res

    def cleanup(self) -> None:
        log.noise(  # type: ignore[attr-defined]
            "Cleanup got called on the audio source:  %r", self
        )
        self._source.cleanup()

    @property
    def frames(self) -> int:
        """
        Number of read frames since this source was opened.
        This is not the total playback time.
        """
        return self._num_reads

    @property
    def session_progress(self) -> float:
        """
        Like progress but only counts frames from this session.
        Adjusts the estimated time by playback speed.
        """
        return (self._num_reads * 0.02) * self._playback_speed

    @property
    def progress(self) -> float:
        """Get an approximate playback progress time."""
        return self._start_time + self.session_progress


class MusicPlayer(EventEmitter, Serializable):
    def __init__(
        self,
        bot: "MusicBot",
        voice_client: VoiceClient,
        playlist: "Playlist",
    ):
        """
        Manage a MusicPlayer with all its bits and bolts.

        :param: bot:  A MusicBot discord client instance.
        :param: voice_client:  a discord.VoiceClient object used for playback.
        :param: playlist:  a collection of playable entries to be played.
        """
        super().__init__()
        self.bot: MusicBot = bot
        self.loop: asyncio.AbstractEventLoop = bot.loop
        self.loopqueue: bool = False
        self.repeatsong: bool = False
        self.voice_client: VoiceClient = voice_client
        self.playlist: Playlist = playlist
        self.autoplaylist: List[str] = []
        self.state: MusicPlayerState = MusicPlayerState.STOPPED
        self.skip_state: SkipState = SkipState()
        self.karaoke_mode: bool = False
        self.guild_or_net_unavailable: bool = False
        self.paused_auto: bool = False

        self._volume = bot.config.default_volume
        self._play_lock = asyncio.Lock()
        self._current_player: Optional[VoiceClient] = None
        self._current_entry: Optional[EntryTypes] = None
        self._stderr_future: Optional[AsyncFuture] = None

        self._source: Optional[SourcePlaybackCounter] = None

        self.playlist.on("entry-added", self.on_entry_added)
        self.playlist.on("entry-failed", self.on_entry_failed)

    @property
    def volume(self) -> float:
        """Get the volume level as last set by config or command."""
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        """
        Set volume to the given `value` and immediately apply it to any
        active playback source.
        """
        self._volume = value
        if self._source:
            if isinstance(self._source._source, PCMVolumeTransformer):
                self._source._source.volume = value
            # if isinstance(self._source._source, FFmpegOpusAudio):

    def on_entry_added(
        self, playlist: "Playlist", entry: EntryTypes, defer_serialize: bool = False
    ) -> None:
        """
        Event dispatched by Playlist when an entry is added to the queue.
        """
        self.emit(
            "entry-added",
            player=self,
            playlist=playlist,
            entry=entry,
            defer_serialize=defer_serialize,
        )

    def on_entry_failed(self, entry: EntryTypes, error: Exception) -> None:
        """
        Event dispatched by Playlist when an entry failed to ready or play.
        """
        self.emit("error", player=self, entry=entry, ex=error)

    def skip(self) -> None:
        """Skip the current playing entry but just killing playback."""
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.skip() is called:  %s", repr(self)
        )
        self._kill_current_player()

    def stop(self) -> None:
        """
        Immediately halt playback, killing current player source, setting
        state to stopped and emitting an event.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.stop() is called:  %s", repr(self)
        )
        self.state = MusicPlayerState.STOPPED
        self._kill_current_player()

        self.emit("stop", player=self)

    def resume(self) -> None:
        """
        Resume the player audio playback if it was paused and we have a
        VoiceClient playback source.
        If MusicPlayer was paused but the VoiceClient player is missing,
        do something odd and set state to playing but kill the player...
        """
        if self.guild_or_net_unavailable:
            log.warning("Guild or network unavailable, cannot resume playback.")
            return

        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.resume() is called:  %s", repr(self)
        )
        if self.is_paused and self._current_player:
            self._current_player.resume()
            self.state = MusicPlayerState.PLAYING
            self.emit("resume", player=self, entry=self.current_entry)
            return

        if self.is_paused and not self._current_player:
            self.state = MusicPlayerState.PLAYING
            self._kill_current_player()
            return

        raise ValueError(f"Cannot resume playback from state {self.state}")

    def pause(self) -> None:
        """
        Suspend player audio playback and emit an event, if the player was playing.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.pause() is called:  %s", repr(self)
        )
        if self.is_playing:
            self.state = MusicPlayerState.PAUSED

            if self._current_player:
                self._current_player.pause()

            self.emit("pause", player=self, entry=self.current_entry)
            return

        if self.is_paused:
            return

        raise ValueError(f"Cannot pause a MusicPlayer in state {self.state}")

    def kill(self) -> None:
        """
        Set the state of the bot to Dead, clear all events and playlists,
        then kill the current VoiceClient source player.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.kill() is called:  %s", repr(self)
        )
        self.state = MusicPlayerState.DEAD
        self.playlist.clear()
        self._events.clear()
        self._kill_current_player()

    def _playback_finished(self, error: Optional[Exception] = None) -> None:
        """
        Event fired by discord.VoiceClient after playback has finished
        or when playback stops due to an error.
        This function is responsible tidying the queue post-playback,
        propagating player error or finished-playing events, and
        triggering the media file cleanup task.

        :param: error:  An exception, if any, raised by playback.
        """
        # Ensure the stderr stream reader for ffmpeg is exited.
        if (
            isinstance(self._stderr_future, asyncio.Future)
            and not self._stderr_future.done()
        ):
            self._stderr_future.set_result(True)

        entry = self._current_entry
        if entry is None:
            log.debug("Playback finished, but _current_entry is None.")
            return

        if self.repeatsong:
            self.playlist.entries.appendleft(entry)
        elif self.loopqueue:
            self.playlist.entries.append(entry)

        # TODO: investigate if this is cruft code or not.
        if self._current_player:
            if hasattr(self._current_player, "after"):
                self._current_player.after = None
            self._kill_current_player()

        self._current_entry = None
        self._source = None
        self.stop()

        # if an error was set, report it and return...
        if error:
            self.emit("error", player=self, entry=entry, ex=error)
            return

        # if a exception is found in the ffmpeg stderr stream, report it and return...
        if (
            isinstance(self._stderr_future, asyncio.Future)
            and self._stderr_future.done()
            and self._stderr_future.exception()
        ):
            # I'm not sure that this would ever not be done if it gets to this point
            # unless ffmpeg is doing something highly questionable
            self.emit(
                "error", player=self, entry=entry, ex=self._stderr_future.exception()
            )
            return

        # ensure file cleanup is handled if nothing was wrong with playback.
        if not self.bot.config.save_videos and entry:
            self.bot.create_task(
                self._handle_file_cleanup(entry), name="MB_CacheCleanup"
            )

        # finally, tell the rest of MusicBot that playback is done.
        self.emit("finished-playing", player=self, entry=entry)

    def _kill_current_player(self) -> bool:
        """
        If there is a current player source, attempt to stop it, then
        say "Garbage day!" and set it to None anyway.
        """
        if self._current_player:
            try:
                self._current_player.stop()
            except OSError:
                log.noise(  # type: ignore[attr-defined]
                    "Possible Warning from kill_current_player()", exc_info=True
                )

            self._current_player = None
            return True

        return False

    def play(self, _continue: bool = False) -> None:
        """
        Immediately try to gracefully play the next entry in the queue.
        If there is already an entry, but player is paused, playback will
        resume instead of playing a new entry.
        If the player is dead, this will silently return.

        :param: _continue:  Force a player that is not dead or stopped to
            start a new playback source anyway.
        """
        log.noise(  # type: ignore[attr-defined]
            "MusicPlayer.play() is called:  %s", repr(self)
        )
        self.bot.create_task(self._play(_continue=_continue), name="MB_Play")

    async def _play(self, _continue: bool = False) -> None:
        """
        Plays the next entry from the playlist, or resumes playback of the current entry if paused.
        """
        if self.is_dead:
            log.voicedebug(  # type: ignore[attr-defined]
                "MusicPlayer is dead, cannot play."
            )
            return

        if self.guild_or_net_unavailable:
            log.warning("Guild or network unavailable, cannot start playback.")
            return

        if self.is_paused and self._current_player:
            log.voicedebug(  # type: ignore[attr-defined]
                "MusicPlayer was previously paused, resuming current player."
            )
            return self.resume()

        if self._play_lock.locked():
            log.voicedebug(  # type: ignore[attr-defined]
                "MusicPlayer already locked for playback, this call is ignored."
            )
            return

        async with self._play_lock:
            if self.is_stopped or _continue:
                # Get the entry before we try to ready it, so it can be passed to error callbacks.
                entry_up_next = self.playlist.peek()
                try:
                    entry = await self.playlist.get_next_entry()
                except IndexError as e:
                    log.warning("Failed to get next entry.", exc_info=e)
                    self.emit("error", player=self, entry=entry_up_next, ex=e)
                    entry = None
                except Exception as e:  # pylint: disable=broad-exception-caught
                    log.warning("Failed to process entry for playback.", exc_info=e)
                    self.emit("error", player=self, entry=entry_up_next, ex=e)
                    entry = None

                # If nothing left to play, transition to the stopped state.
                if not entry:
                    self.stop()
                    return

                # In-case there was a player, kill it. RIP.
                self._kill_current_player()

                boptions = "-nostdin"
                aoptions = "-vn -sn -dn"  # "-b:a 192k"
                if isinstance(entry, (URLPlaylistEntry, LocalFilePlaylistEntry)):
                    # check for after-options, usually filters for speed and EQ.
                    if entry.aoptions and not self.bot.config.use_opus_probe:
                        aoptions += f" {entry.aoptions}"
                    # check for before options, currently just -ss here.
                    if entry.boptions:
                        boptions += f" {entry.boptions}"

                stderr_io = io.BytesIO()

                if self.bot.config.use_opus_probe:
                    # Note: volume adjustment is not easily supported with Opus.
                    # ffmpeg volume filter seems to require encoding audio to work.
                    source: FFmpegSources = await FFmpegOpusAudio.from_probe(
                        entry.filename,
                        method="native",
                        before_options=boptions,
                        options=aoptions,
                        stderr=stderr_io,
                    )
                else:
                    source = PCMVolumeTransformer(
                        FFmpegPCMAudio(
                            entry.filename,
                            before_options=boptions,
                            options=aoptions,
                            stderr=stderr_io,
                        ),
                        self.volume,
                    )

                self._source = SourcePlaybackCounter(
                    source,
                    start_time=entry.start_time,
                    playback_speed=entry.playback_speed,
                )
                log.ffmpeg(  # type: ignore[attr-defined]
                    "Creating player with options: ffmpeg %(before)s -i %(input)s %(after)s",
                    {"before": boptions, "input": entry.filename, "after": aoptions},
                )
                log.voicedebug(  # type: ignore[attr-defined]
                    "Playing %(source)r using %(client)r",
                    {"source": self._source, "client": self.voice_client},
                )
                self.voice_client.play(self._source, after=self._playback_finished)

                self._current_player = self.voice_client

                # I need to add ytdl hooks
                self.state = MusicPlayerState.PLAYING
                self._current_entry = entry

                self._stderr_future = asyncio.Future()

                stderr_thread = Thread(
                    target=filter_stderr,
                    args=(stderr_io, self._stderr_future),
                    name="MB_FFmpegStdErrReader",
                )

                stderr_thread.start()

                self.emit("play", player=self, entry=entry)

    async def _handle_file_cleanup(self, entry: EntryTypes) -> None:
        """
        A helper used to clean up media files via call-later, when file
        cache is not enabled.
        """
        if not isinstance(entry, StreamPlaylistEntry):
            if any(entry.filename == e.filename for e in self.playlist.entries):
                log.debug(
                    "Skipping deletion of '%s', found song in queue",
                    entry.filename,
                )
            else:
                log.debug("Deleting file:  %s", os.path.relpath(entry.filename))
                filename = entry.filename
                for _ in range(3):
                    try:
                        os.unlink(filename)
                        log.debug("File deleted:  %s", filename)
                        break
                    except PermissionError as e:
                        if e.errno == 32:  # File is in use
                            log.warning("Cannot delete file, it is currently in use.")
                        else:
                            log.warning(
                                "Cannot delete file due to a permission error.",
                                exc_info=True,
                            )
                    except FileNotFoundError:
                        log.warning(
                            "Cannot delete file, it was not found.",
                            exc_info=True,
                        )
                        break
                    except (OSError, IsADirectoryError):
                        log.warning(
                            "Error while trying to delete file.",
                            exc_info=True,
                        )
                        break
                else:
                    log.debug("Could not delete file, giving up and moving on")

    def __json__(self) -> Dict[str, Any]:
        return self._enclose_json(
            {
                "current_entry": {
                    "entry": self.current_entry,
                    "progress": self.progress if self.progress > 1 else None,
                },
                "entries": self.playlist,
            }
        )

    @classmethod
    def _deserialize(
        cls,
        raw_json: Dict[str, Any],
        bot: Optional["MusicBot"] = None,
        voice_client: Optional[VoiceClient] = None,
        playlist: Optional["Playlist"] = None,
        **kwargs: Any,
    ) -> "MusicPlayer":
        assert bot is not None, cls._bad("bot")
        assert voice_client is not None, cls._bad("voice_client")
        assert playlist is not None, cls._bad("playlist")

        player = cls(bot, voice_client, playlist)

        data_pl = raw_json.get("entries")
        if data_pl and data_pl.entries:
            player.playlist.entries = data_pl.entries

        current_entry_data = raw_json["current_entry"]
        if current_entry_data["entry"]:
            entry = current_entry_data["entry"]
            progress = current_entry_data["progress"]
            if progress and isinstance(
                entry, (URLPlaylistEntry, LocalFilePlaylistEntry)
            ):
                entry.set_start_time(progress)
            player.playlist.entries.appendleft(current_entry_data["entry"])
        return player

    @classmethod
    def from_json(
        cls,
        raw_json: str,
        bot: "MusicBot",  # pylint: disable=unused-argument
        voice_client: VoiceClient,  # pylint: disable=unused-argument
        playlist: "Playlist",  # pylint: disable=unused-argument
    ) -> Optional["MusicPlayer"]:
        """
        Create a MusicPlayer instance from serialized `raw_json` string data.
        The remaining arguments are made available to the MusicPlayer
        and other serialized instances via call frame inspection.
        """
        try:
            obj = json.loads(raw_json, object_hook=Serializer.deserialize)
            if isinstance(obj, MusicPlayer):
                return obj
            log.error(
                "Deserialize returned an object that is not a MusicPlayer:  %s",
                type(obj),
            )
            return None
        except json.JSONDecodeError:
            log.exception("Failed to deserialize player")
            return None

    @property
    def current_entry(self) -> Optional[EntryTypes]:
        """Get the currently playing entry if there is one."""
        return self._current_entry

    @property
    def is_playing(self) -> bool:
        """Test if MusicPlayer is in a playing state"""
        return self.state == MusicPlayerState.PLAYING

    @property
    def is_paused(self) -> bool:
        """Test if MusicPlayer is in a paused state"""
        return self.state == MusicPlayerState.PAUSED

    @property
    def is_stopped(self) -> bool:
        """Test if MusicPlayer is in a stopped state"""
        return self.state == MusicPlayerState.STOPPED

    @property
    def is_dead(self) -> bool:
        """Test if MusicPlayer is in a dead state"""
        return self.state == MusicPlayerState.DEAD

    @property
    def progress(self) -> float:
        """
        Return a progress value for the media playback.
        """
        if self._source:
            return self._source.progress
        return 0

    @property
    def session_progress(self) -> float:
        """
        Return the estimated playback time of the current playback source.
        Like progress, but does not include any start-time if one was used.
        """
        if self._source:
            return self._source.session_progress
        return 0


# TODO: I need to add a check if the event loop is closed?


def filter_stderr(stderr: io.BytesIO, future: AsyncFuture) -> None:
    """
    Consume a `stderr` bytes stream and check it for errors or warnings.
    Set the given `future` with either an error found in the stream or
    set the future with a successful result.
    """
    last_ex = None
    while not future.done():
        data = stderr.readline()
        if data:
            log.ffmpeg(  # type: ignore[attr-defined]
                "Data from ffmpeg: %s",
                repr(data),
            )
            try:
                if check_stderr(data):
                    sys.stderr.buffer.write(data)
                    sys.stderr.buffer.flush()

            except FFmpegError as e:
                log.ffmpeg(  # type: ignore[attr-defined]
                    "Error from ffmpeg: %s", str(e).strip()
                )
                last_ex = e
                if not future.done():
                    future.set_exception(e)

            except FFmpegWarning as e:
                log.ffmpeg(  # type: ignore[attr-defined]
                    "Warning from ffmpeg:  %s", str(e).strip()
                )
        else:
            time.sleep(0.5)

    if not future.done():
        if last_ex:
            future.set_exception(last_ex)
        else:
            future.set_result(True)


def check_stderr(data: bytes) -> bool:
    """
    Inspect `data` from a subprocess call's stderr output for specific
    messages and raise them as a suitable exception.

    :returns:  True if nothing was detected or nothing could be detected.

    :raises: musicbot.exceptions.FFmpegWarning
        If a warning level message was detected in the `data`
    :raises: musicbot.exceptions.FFmpegError
        If an error message was detected in the `data`
    """
    ddata = ""
    try:
        ddata = data.decode("utf8")
    except UnicodeDecodeError:
        log.ffmpeg(  # type: ignore[attr-defined]
            "Unknown error decoding message from ffmpeg", exc_info=True
        )
        return True  # fuck it

    log.ffmpeg("Decoded data from ffmpeg: %s", ddata)  # type: ignore[attr-defined]

    # TODO: Regex
    warnings = [
        "Header missing",
        "Estimating duration from birate, this may be inaccurate",
        "Using AVStream.codec to pass codec parameters to muxers is deprecated, use AVStream.codecpar instead.",
        "Application provided invalid, non monotonically increasing dts to muxer in stream",
        "Last message repeated",
        "Failed to send close message",
        "decode_band_types: Input buffer exhausted before END element found",
    ]
    errors = [
        "Invalid data found when processing input",  # need to regex this properly, its both a warning and an error
    ]

    if any(msg in ddata for msg in warnings):
        raise FFmpegWarning(ddata)

    if any(msg in ddata for msg in errors):
        raise FFmpegError(ddata)

    return True


# if redistributing ffmpeg is an issue, it can be downloaded from here:
#  - http://ffmpeg.zeranoe.com/builds/win32/static/ffmpeg-latest-win32-static.7z
#  - http://ffmpeg.zeranoe.com/builds/win64/static/ffmpeg-latest-win64-static.7z
#
# Extracting bin/ffmpeg.exe, bin/ffplay.exe, and bin/ffprobe.exe should be fine
# However, the files are in 7z format so meh
# I don't know if we can even do this for the user, at most we open it in the browser
# I can't imagine the user is so incompetent that they can't pull 3 files out of it...
# ...
# ...right?

# Get duration with ffprobe
#   ffprobe.exe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -sexagesimal filename.mp3
# This is also how I fix the format checking issue for now
# ffprobe -v quiet -print_format json -show_format stream

# Normalization filter
# -af dynaudnorm
import asyncio
import datetime
import logging
from collections import deque
from itertools import islice
from random import shuffle
from typing import (
    TYPE_CHECKING,
    Any,
    Deque,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)

import discord

from .constants import DEFAULT_PRE_DOWNLOAD_DELAY
from .constructs import Serializable
from .entry import LocalFilePlaylistEntry, StreamPlaylistEntry, URLPlaylistEntry
from .exceptions import ExtractionError, InvalidDataError, WrongEntryTypeError
from .lib.event_emitter import EventEmitter

if TYPE_CHECKING:
    from .bot import MusicBot
    from .downloader import YtdlpResponseDict
    from .player import MusicPlayer

# type aliases
EntryTypes = Union[URLPlaylistEntry, StreamPlaylistEntry, LocalFilePlaylistEntry]

GuildMessageableChannels = Union[
    discord.VoiceChannel,
    discord.StageChannel,
    discord.Thread,
    discord.TextChannel,
]

log = logging.getLogger(__name__)


class Playlist(EventEmitter, Serializable):
    """
    A playlist that manages the queue of songs that will be played.
    """

    def __init__(self, bot: "MusicBot") -> None:
        """
        Manage a serializable, event-capable playlist of entries made up
        of validated extraction information.
        """
        super().__init__()
        self.bot: MusicBot = bot
        self.loop: asyncio.AbstractEventLoop = bot.loop
        self.entries: Deque[EntryTypes] = deque()

    def __iter__(self) -> Iterator[EntryTypes]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def shuffle(self) -> None:
        """Shuffle the deque of entries, in place."""
        shuffle(self.entries)

    def clear(self) -> None:
        """Clears the deque of entries."""
        self.entries.clear()

    def get_entry_at_index(self, index: int) -> EntryTypes:
        """
        Uses deque rotate to seek to the given `index` and reference the
        entry at that position.
        """
        self.entries.rotate(-index)
        entry = self.entries[0]
        self.entries.rotate(index)
        return entry

    def delete_entry_at_index(self, index: int) -> EntryTypes:
        """Remove and return the entry at the given index."""
        self.entries.rotate(-index)
        entry = self.entries.popleft()
        self.entries.rotate(index)
        return entry

    def insert_entry_at_index(self, index: int, entry: EntryTypes) -> None:
        """Add entry to the queue at the given index."""
        self.entries.rotate(-index)
        self.entries.appendleft(entry)
        self.entries.rotate(index)

    async def add_stream_from_info(
        self,
        info: "YtdlpResponseDict",
        *,
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
        head: bool = False,
        defer_serialize: bool = False,
    ) -> Tuple[StreamPlaylistEntry, int]:
        """
        Use the given `info` to create a StreamPlaylistEntry and add it
        to the queue.
        If the entry is the first in the queue, it will be called to ready
        for playback.

        :param: info:  Extracted info for this entry, even fudged.
        :param: head:  Toggle adding to the front of the queue.
        :param: defer_serialize:  Signal to defer serialization steps.
            Useful if many entries are added at once

        :returns:  A tuple with the entry object, and its position in the queue.
        """

        log.noise(  # type: ignore[attr-defined]
            "Adding stream entry for URL:  %(url)s",
            {"url": info.url},
        )
        entry = StreamPlaylistEntry(
            self,
            info,
            author=author,
            channel=channel,
        )
        self._add_entry(entry, head=head, defer_serialize=defer_serialize)
        return entry, len(self.entries)

    async def add_entry_from_info(
        self,
        info: "YtdlpResponseDict",
        *,
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
        head: bool = False,
        defer_serialize: bool = False,
    ) -> Tuple[EntryTypes, int]:
        """
        Checks given `info` to determine if media is streaming or has a
        stream-able content type, then adds the resulting entry to the queue.
        If the entry is the first entry in the queue, it will be called
        to ready for playback.

        :param info: The extraction data of the song to add to the playlist.
        :param head: Add to front of queue instead of the end.
        :param defer_serialize:  Signal that serialization steps should be deferred.

        :returns: the entry & it's position in the queue.

        :raises: ExtractionError  If data is missing or the content type is invalid.
        :raises: WrongEntryTypeError  If the info is identified as a playlist.
        """

        if not info:
            raise ExtractionError("Could not extract information")

        # this should, in theory, never happen.
        if info.ytdl_type == "playlist":
            raise WrongEntryTypeError("This is a playlist.")

        # check if this is a local file entry.
        if info.ytdl_type == "local":
            return await self.add_local_file_entry(
                info,
                author=author,
                channel=channel,
                head=head,
                defer_serialize=defer_serialize,
            )

        # check if this is a stream, just in case.
        if info.is_stream:
            log.debug("Entry info appears to be a stream, adding stream entry...")
            return await self.add_stream_from_info(
                info,
                author=author,
                channel=channel,
                head=head,
                defer_serialize=defer_serialize,
            )

        # TODO: Extract this to its own function
        if any(info.extractor.startswith(x) for x in ["generic", "Dropbox"]):
            content_type = info.http_header("content-type", None)

            if content_type:
                if content_type.startswith(("application/", "image/")):
                    if not any(x in content_type for x in ("/ogg", "/octet-stream")):
                        # How does a server say `application/ogg` what the actual fuck
                        raise ExtractionError(
                            "Invalid content type `%(type)s` for URL: %(url)s",
                            fmt_args={"type": content_type, "url": info.url},
                        )

                elif (
                    content_type.startswith("text/html") and info.extractor == "generic"
                ):
                    log.warning(
                        "Got text/html for content-type, this might be a stream."
                    )
                    return await self.add_stream_from_info(info, head=head)
                    # TODO: Check for shoutcast/icecast

                elif not content_type.startswith(("audio/", "video/")):
                    log.warning(
                        'Questionable content-type "%(type)s" for url:  %(url)s',
                        {"type": content_type, "url": info.url},
                    )

        log.noise(  # type: ignore[attr-defined]
            "Adding URLPlaylistEntry for: %(subject)s",
            {"subject": info.input_subject},
        )
        entry = URLPlaylistEntry(self, info, author=author, channel=channel)
        self._add_entry(entry, head=head, defer_serialize=defer_serialize)
        return entry, (1 if head else len(self.entries))

    async def add_local_file_entry(
        self,
        info: "YtdlpResponseDict",
        *,
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
        head: bool = False,
        defer_serialize: bool = False,
    ) -> Tuple[LocalFilePlaylistEntry, int]:
        """
        Adds a local media file entry to the playlist.
        """
        log.noise(  # type: ignore[attr-defined]
            "Adding LocalFilePlaylistEntry for: %(subject)s",
            {"subject": info.input_subject},
        )
        entry = LocalFilePlaylistEntry(self, info, author=author, channel=channel)
        self._add_entry(entry, head=head, defer_serialize=defer_serialize)
        return entry, (1 if head else len(self.entries))

    async def import_from_info(
        self,
        info: "YtdlpResponseDict",
        head: bool,
        ignore_video_id: str = "",
        author: Optional["discord.Member"] = None,
        channel: Optional[GuildMessageableChannels] = None,
    ) -> Tuple[List[EntryTypes], int]:
        """
        Validates the songs from `info` and queues them to be played.

        Returns a list of entries that have been queued, and the queue
        position where the first entry was added.

        :param: info:  YoutubeDL extraction data containing multiple entries.
        :param: head:  Toggle adding the entries to the front of the queue.
        """
        position = 1 if head else len(self.entries) + 1
        entry_list = []
        baditems = 0
        entries = info.get_entries_objects()
        author_perms = None
        defer_serialize = True

        if author:
            author_perms = self.bot.permissions.for_user(author)

        if head:
            entries.reverse()

        track_number = 0
        for item in entries:
            # count tracks regardless of conditions, used for missing track names
            # and also defers serialization of the queue for playlists.
            track_number += 1
            # Ignore playlist entry when it comes from compound links.
            if ignore_video_id and ignore_video_id == item.video_id:
                log.debug(
                    "Ignored video from compound playlist link with ID:  %s",
                    item.video_id,
                )
                baditems += 1
                continue

            # Check if the item is in the song block list.
            if self.bot.config.song_blocklist_enabled and (
                self.bot.config.song_blocklist.is_blocked(item.url)
                or self.bot.config.song_blocklist.is_blocked(item.title)
            ):
                log.info(
                    "Not allowing entry that is in song block list:  %(title)s  URL: %(url)s",
                    {"title": item.title, "url": item.url},
                )
                baditems += 1
                continue

            # Exclude entries over max permitted duration.
            if (
                author_perms
                and author_perms.max_song_length
                and item.duration > author_perms.max_song_length
            ):
                log.debug(
                    "Ignoring song in entries by '%s', duration longer than permitted maximum.",
                    author,
                )
                baditems += 1
                continue

            # Check youtube data to preemptively avoid adding Private or Deleted videos to the queue.
            if info.extractor.startswith("youtube") and (
                "[private video]" == item.get("title", "").lower()
                or "[deleted video]" == item.get("title", "").lower()
            ):
                log.warning(
                    "Not adding YouTube video because it is marked private or deleted:  %s",
                    item.get_playable_url(),
                )
                baditems += 1
                continue

            # Soundcloud playlists don't get titles in flat extraction. A bug maybe?
            # Anyway we make a temp title here, the real one is fetched at play.
            if "title" in info and "title" not in item:
                item["title"] = f"{info.title} - #{track_number}"

            if track_number >= info.entry_count:
                defer_serialize = False

            try:
                entry, _pos = await self.add_entry_from_info(
                    item,
                    head=head,
                    defer_serialize=defer_serialize,
                    author=author,
                    channel=channel,
                )
                entry_list.append(entry)
            except (WrongEntryTypeError, ExtractionError):
                baditems += 1
                log.warning("Could not add item")
                log.debug("Item: %s", item, exc_info=True)

        if baditems:
            log.info("Skipped %s bad entries", baditems)

        if head:
            entry_list.reverse()
        return entry_list, position

    def get_next_song_from_author(
        self, author: "discord.abc.User"
    ) -> Optional[EntryTypes]:
        """
        Get the next song in the queue that was added by the given `author`
        """
        for entry in self.entries:
            if entry.author == author:
                return entry

        return None

    def reorder_for_round_robin(self) -> None:
        """
        Reorders the current queue for round-robin, one song per author.
        Entries added by the auto playlist will be removed.
        """
        new_queue: Deque[EntryTypes] = deque()
        all_authors: List[discord.abc.User] = []

        # Make a list of unique authors from the current queue.
        for entry in self.entries:
            if entry.author and entry.author not in all_authors:
                all_authors.append(entry.author)

        # If all queue entries have no author, do nothing.
        if len(all_authors) == 0:
            return

        # Loop over the queue and organize it by requesting author.
        # This will remove entries which are added by the auto-playlist.
        request_counter = 0
        song: Optional[EntryTypes] = None
        while self.entries:
            log.everything(  # type: ignore[attr-defined]
                "Reorder looping over entries."
            )

            # Do not continue if we have no more authors.
            if len(all_authors) == 0:
                break

            # Reset the requesting author if needed.
            if request_counter >= len(all_authors):
                request_counter = 0

            song = self.get_next_song_from_author(all_authors[request_counter])

            # Remove the authors with no further songs.
            if song is None:
                all_authors.pop(request_counter)
                continue

            new_queue.append(song)
            self.entries.remove(song)
            request_counter += 1

        self.entries = new_queue

    def _add_entry(
        self, entry: EntryTypes, *, head: bool = False, defer_serialize: bool = False
    ) -> None:
        """
        Handle appending the `entry` to the queue. If the entry is he first,
        the entry will create a future to download itself.

        :param: head:  Toggle adding to the front of the queue.
        :param: defer_serialize:  Signal to events that serialization should be deferred.
        """
        if head:
            self.entries.appendleft(entry)
        else:
            self.entries.append(entry)

        if self.bot.config.round_robin_queue and not entry.from_auto_playlist:
            self.reorder_for_round_robin()

        self.emit(
            "entry-added", playlist=self, entry=entry, defer_serialize=defer_serialize
        )

    async def get_next_entry(self) -> Any:
        """
        A coroutine which will return the next song or None if no songs left to play.

        Additionally, if predownload_next is set to True, it will attempt to download the next
        song to be played - so that it's ready by the time we get to it.
        """
        if not self.entries:
            return None

        entry = self.entries.popleft()
        self.bot.create_task(
            self._pre_download_entry_after_next(entry),
            name="MB_PreDownloadNextUp",
        )

        return await entry.get_ready_future()

    async def _pre_download_entry_after_next(self, last_entry: EntryTypes) -> None:
        """
        Enforces a delay before doing pre-download of the "next" song.
        Should only be called from get_next_entry() after pop.
        """
        if not self.bot.config.pre_download_next_song:
            return

        if not self.entries:
            return

        # get the next entry to pre-download before we wait.
        next_entry = self.peek()

        await asyncio.sleep(DEFAULT_PRE_DOWNLOAD_DELAY)

        if next_entry and next_entry != last_entry:
            log.everything(  # type: ignore[attr-defined]
                "Pre-downloading next track:  %r", next_entry
            )
            next_entry.get_ready_future()

    def peek(self) -> Optional[EntryTypes]:
        """
        Returns the next entry that should be scheduled to be played.
        """
        if self.entries:
            return self.entries[0]
        return None

    async def estimate_time_until(
        self, position: int, player: "MusicPlayer"
    ) -> datetime.timedelta:
        """
        (very) Roughly estimates the time till the queue will reach given `position`.

        :param: position:  The index in the queue to reach.
        :param: player:  MusicPlayer instance this playlist should belong to.

        :returns: A datetime.timedelta object with the estimated time.

        :raises: musicbot.exceptions.InvalidDataError  if duration data cannot be calculated.
        """
        if any(e.duration is None for e in islice(self.entries, position - 1)):
            raise InvalidDataError("no duration data")

        estimated_time = sum(
            e.duration_td.total_seconds() for e in islice(self.entries, position - 1)
        )

        # When the player plays a song, it eats the first playlist item, so we just have to add the time back
        if not player.is_stopped and player.current_entry:
            if player.current_entry.duration is None:
                raise InvalidDataError("no duration data in current entry")

            estimated_time += (
                player.current_entry.duration_td.total_seconds() - player.progress
            )

        return datetime.timedelta(seconds=estimated_time)

    def count_for_user(self, user: "discord.abc.User") -> int:
        """Get a sum of entries added to the playlist by the given `user`"""
        return sum(1 for e in self.entries if e.author == user)

    def __json__(self) -> Dict[str, Any]:
        return self._enclose_json({"entries": list(self.entries)})

    @classmethod
    def _deserialize(
        cls, raw_json: Dict[str, Any], bot: Optional["MusicBot"] = None, **kwargs: Any
    ) -> "Playlist":
        assert bot is not None, cls._bad("bot")
        # log.debug("Deserializing playlist")
        pl = cls(bot)

        for entry in raw_json["entries"]:
            pl.entries.append(entry)

        # TODO: create a function to init downloading (since we don't do it here)?
        return pl
import asyncio
import asyncio.exceptions
import base64
import logging
import re
import time
from json import JSONDecodeError
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from .exceptions import SpotifyError
from .i18n import _L

log = logging.getLogger(__name__)


"""
This is not the "right" way to do this.
I -should- build an extractor to register with ytdlp instead.
This will do for now though.
"""


class SpotifyObject:
    """Base class for parsed spotify response objects."""

    def __init__(self, data: Dict[str, Any], origin_url: Optional[str] = None) -> None:
        """
        Manage basic data container properties common to all SpotifyObject types.
        """
        self.origin_url: Optional[str]

        self.data: Dict[str, Any] = data

        if origin_url:
            self.origin_url = origin_url
        else:
            self.origin_url = self.spotify_url

    @staticmethod
    def is_type(data: Dict[str, Any], spotify_type: str) -> bool:
        """Verify if data has a 'type' key matching spotify_type value"""
        type_str = data.get("type", None)
        if type_str == spotify_type:
            return True
        return False

    @staticmethod
    def is_track_data(data: Dict[str, Any]) -> bool:
        """Check if given Spotify API response `data` has 'track' type."""
        return SpotifyObject.is_type(data, "track")

    @staticmethod
    def is_playlist_data(data: Dict[str, Any]) -> bool:
        """Check if given Spotify API response `data` has 'playlist' type."""
        return SpotifyObject.is_type(data, "playlist")

    @staticmethod
    def is_album_data(data: Dict[str, Any]) -> bool:
        """Check if given Spotify API response `data` has 'album' type."""
        return SpotifyObject.is_type(data, "album")

    @property
    def spotify_type(self) -> str:
        """Returns the type string of the object as reported by the API data."""
        return str(self.data.get("type", ""))

    @property
    def spotify_id(self) -> str:
        """Returns the Spotify ID of the object, as reported by the API data."""
        return str(self.data.get("id", ""))

    @property
    def spotify_url(self) -> str:
        """Returns the spotify external url for this object, if it exists in the API data."""
        exurls = self.data.get("external_urls", "")
        if exurls:
            return str(exurls.get("spotify", ""))
        return ""

    @property
    def spotify_uri(self) -> str:
        """Returns the "Spotify URI" for this object if available."""
        return str(self.data.get("uri", ""))

    @property
    def name(self) -> str:
        """Returns the track/playlist/album name given by spotify."""
        return str(self.data.get("name", ""))

    @property
    def ytdl_type(self) -> str:
        """A suitable string for ytdlp _type field."""
        return "url" if self.spotify_type == "track" else "playlist"

    def to_ytdl_dict(self) -> Dict[str, Any]:
        """Returns object data in a format similar to ytdl."""
        return {
            "_type": self.ytdl_type,
            "id": self.spotify_uri,
            "original_url": self.origin_url,
            "webpage_url": self.spotify_url,
            "extractor": "spotify:musicbot",
            "extractor_key": "SpotifyMusicBot",
        }


class SpotifyTrack(SpotifyObject):
    """Track data for an individual track, parsed from spotify API response data."""

    def __init__(
        self, track_data: Dict[str, Any], origin_url: Optional[str] = None
    ) -> None:
        super().__init__(track_data, origin_url)
        if not SpotifyObject.is_track_data(track_data):
            raise SpotifyError(
                "Invalid track_data, must be of type `track` got `%(type)s`",
                fmt_args={"type": self.spotify_type},
            )

    @property
    def artist_name(self) -> str:
        """Get the first artist name, if any, from track data. Can be empty string."""
        artists = self.data.get("artists", None)
        if artists:
            return str(artists[0].get("name", ""))
        return ""

    @property
    def artist_names(self) -> List[str]:
        """Get all artist names for track in a list of strings. List may be empty"""
        artists = self.data.get("artists", [])
        names = []
        for artist in artists:
            n = artist.get("name", None)
            if n:
                names.append(n)
        return names

    def get_joined_artist_names(self, join_with: str = " ") -> str:
        """Gets all non-empty artist names joined together as a string."""
        return join_with.join(self.artist_names)

    def get_track_search_string(
        self, format_str: str = "{0} {1}", join_artists_with: str = " "
    ) -> str:
        """Get track title with artist names for searching against"""
        return format_str.format(
            self.get_joined_artist_names(join_artists_with),
            self.name,
        )

    @property
    def duration(self) -> float:
        """Calculate duration in seconds from track 'duration_ms' value."""
        return float(self.data.get("duration_ms", 0)) / 1000

    @property
    def thumbnail_url(self) -> str:
        """
        Get the largest available thumbnail URL for this track.
        May return an empty string.
        Note: this URL will expire in less than a day.
        """
        album = self.data.get("album", {})
        imgs = album.get("images", None)
        if imgs:
            return str(imgs[0].get("url", ""))
        return ""

    def to_ytdl_dict(self, as_single: bool = True) -> Dict[str, Any]:
        url: Optional[str]
        if as_single:
            url = self.get_track_search_string("ytsearch:{0} {1}")
        else:
            url = self.spotify_url
        return {
            **super().to_ytdl_dict(),
            "title": self.name,
            "artists": self.artist_names,
            "url": url,
            "search_terms": self.get_track_search_string(),
            "thumbnail": self.thumbnail_url,
            "duration": self.duration,
            "playlist_count": 1,
        }


class SpotifyAlbum(SpotifyObject):
    """Album object with all or partial tracks, as parsed from spotify API response data."""

    def __init__(
        self, album_data: Dict[str, Any], origin_url: Optional[str] = None
    ) -> None:
        if not SpotifyObject.is_album_data(album_data):
            raise ValueError("Invalid album_data, must be of type 'album'")
        super().__init__(album_data, origin_url)
        self._track_objects: List[SpotifyTrack] = []

        self._create_track_objects()

    def _create_track_objects(self) -> None:
        """
        Method used to massage Spotify API data into individual
        SpotifyTrack objects, or throw a fit if it fails.

        :raises: ValueError  if tracks are invalid or tracks data is missing.
        """
        tracks_data = self.data.get("tracks", None)
        if not tracks_data:
            raise ValueError("Invalid album_data, missing tracks key")

        items = tracks_data.get("items", None)
        if not items:
            raise ValueError("Invalid album_data, missing items key in tracks")

        # albums use a slightly different "SimplifiedTrackObject" without the album key.
        # each item is a track, versus having a "track" key for TrackObject data, like Playlists do.
        for item in items:
            self._track_objects.append(SpotifyTrack(item))

    @property
    def track_objects(self) -> List[SpotifyTrack]:
        """List of SpotifyTrack objects loaded with the playlist API data."""
        return self._track_objects

    @property
    def track_urls(self) -> List[str]:
        """List of spotify URLs for all tracks in this playlist data."""
        return [x.spotify_url for x in self.track_objects]

    @property
    def track_count(self) -> int:
        """Get number of total tracks in playlist, as reported by API"""
        tracks = self.data.get("tracks", {})
        return int(tracks.get("total", 0))

    @property
    def thumbnail_url(self) -> str:
        """
        Get the largest available thumbnail URL for this album.
        May return an empty string.
        Note: this URL will expire in less than a day.
        """
        imgs = self.data.get("images", None)
        if imgs:
            return str(imgs[0].get("url", ""))
        return ""

    def to_ytdl_dict(self) -> Dict[str, Any]:
        return {
            **super().to_ytdl_dict(),
            "title": self.name,
            "url": "",
            "thumbnail": self.thumbnail_url,
            "playlist_count": self.track_count,
            "entries": [t.to_ytdl_dict(False) for t in self.track_objects],
        }


class SpotifyPlaylist(SpotifyObject):
    """Playlist object with all or partial tracks, as parsed from spotify API response data."""

    def __init__(
        self, playlist_data: Dict[str, Any], origin_url: Optional[str] = None
    ) -> None:
        if not SpotifyObject.is_playlist_data(playlist_data):
            raise ValueError("Invalid playlist_data, must be of type 'playlist'")
        super().__init__(playlist_data, origin_url)
        self._track_objects: List[SpotifyTrack] = []

        self._create_track_objects()

    def _create_track_objects(self) -> None:
        """
        Method used to massage Spotify API data into individual
        SpotifyTrack objects, or throw a fit if it fails.

        :raises: ValueError  if tracks are invalid or tracks data is missing.
        """
        tracks_data = self.data.get("tracks", None)
        if not tracks_data:
            raise ValueError("Invalid playlist_data, missing tracks key")

        items = tracks_data.get("items", None)
        if not items:
            raise ValueError("Invalid playlist_data, missing items key in tracks")

        for item in items:
            if "track" not in item:
                raise ValueError("Invalid playlist_data, missing track key in items")

            track_data = item.get("track", None)
            track_type = track_data.get("type", None)
            if track_data and track_type == "track":
                self._track_objects.append(SpotifyTrack(track_data))
            else:
                log.everything(  # type: ignore[attr-defined]
                    "Ignored non-track entry in playlist with type:  %s",
                    track_type,
                )

    @property
    def track_objects(self) -> List[SpotifyTrack]:
        """List of SpotifyTrack objects loaded with the playlist API data."""
        return self._track_objects

    @property
    def track_urls(self) -> List[str]:
        """List of spotify URLs for all tracks in this playlist data."""
        return [x.spotify_url for x in self.track_objects]

    @property
    def track_count(self) -> int:
        """Get number of total tracks in playlist, as reported by API"""
        tracks = self.data.get("tracks", {})
        return int(tracks.get("total", 0))

    @property
    def tracks_loaded(self) -> int:
        """Get number of valid tracks in the playlist."""
        return len(self._track_objects)

    @property
    def thumbnail_url(self) -> str:
        """
        Get the largest available thumbnail URL for this playlist.
        May return an empty string.
        Note: this URL will expire in less than a day.
        """
        imgs = self.data.get("images", None)
        if imgs:
            return str(imgs[0].get("url", ""))
        return ""

    def to_ytdl_dict(self) -> Dict[str, Any]:
        return {
            **super().to_ytdl_dict(),
            "title": self.name,
            "url": "",
            "thumbnail": self.thumbnail_url,
            "playlist_count": self.track_count,
            "entries": [t.to_ytdl_dict(False) for t in self.track_objects],
        }


class Spotify:
    WEB_TOKEN_URL = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
    OAUTH_TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1/"
    # URL_REGEX allows missing protocol scheme and region code intentionally.
    URL_REGEX = re.compile(r"(?:https?://)?open\.spotify\.com/(?:intl-[\w-]+/)?", re.I)

    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        aiosession: aiohttp.ClientSession,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """
        Manage data and state for this Spotify API session.
        """
        self.client_id: str = client_id or ""
        self.client_secret: str = client_secret or ""
        self.guest_mode: bool = client_id is None or client_secret is None

        self.aiosession = aiosession
        self.loop = loop if loop else asyncio.get_event_loop()

        self._token: Optional[Dict[str, Any]] = None

        self.max_token_tries = 2

    @staticmethod
    def url_to_uri(url: str) -> str:
        """
        Convert a spotify url to a spotify URI string.

        Note: this function assumes `url` is already a valid URL.
        See `downloader.get_url_or_none()` for validating input URLs.
        """
        # strip away query strings and fragments.
        url = urlparse(url)._replace(query="", fragment="").geturl()
        # replace protocol and FQDN with our local "scheme" and clean it up.
        return Spotify.URL_REGEX.sub("spotify:", url).replace("/", ":")

    @staticmethod
    def url_to_parts(url: str) -> List[str]:
        """
        Convert a spotify url to a string list of URI parts.
        If the URL is valid, index 0 will equal "spotify".
        Empty list is returned if URL is not a valid spotify URL.
        """
        uri = Spotify.url_to_uri(url)
        if uri.startswith("spotify:"):
            return uri.split(":")
        return []

    @staticmethod
    def is_url_supported(url: str) -> bool:
        """
        Check if the given `url` is a supported Spotify URL.
        """
        parts = Spotify.url_to_parts(url)
        if not parts:
            return False
        if parts and "spotify" != parts[0]:
            return False
        if parts[1] not in ["track", "album", "playlist"]:
            return False
        if len(parts) < 3:
            return False
        return True

    def api_safe_url(self, url: str) -> str:
        """
        Makes Spotify API URLs in response date "safe" for use in this API.
        Assuming all API URLs in the API response data will begin with the
        API_BASE that we already use, this removes the base URL, so the
        remainder of the URL can then be appended to the API_BASE.

        This prevents data in a Spotify response from sending our API to
        a totally different domain than what API_BASE is set to.
        """
        return url.replace(self.API_BASE, "")

    async def get_spotify_ytdl_data(
        self, spotify_url: str, process: bool = False
    ) -> Dict[str, Any]:
        """
        Uses an `spotify_url` to determine if information can be requested
        and returns a dictionary of data similar in format to that of
        YoutubeDL.extract_info()

        :param: spotify_url:  a URL assumed to be a spotify URL.
        :param: process:  Enable subsequent API calls to fetch all data about the object.
        """
        data: SpotifyObject
        parts = Spotify.url_to_parts(spotify_url)
        obj_type = parts[1]
        spotify_id = parts[-1]
        if obj_type == "track":
            data = await self.get_track_object(spotify_id)
            data.origin_url = spotify_url
            return data.to_ytdl_dict()

        if obj_type == "album":
            if process:
                data = await self.get_album_object_complete(spotify_id)
                data.origin_url = spotify_url
                return data.to_ytdl_dict()
            data = await self.get_album_object(spotify_id)
            data.origin_url = spotify_url
            return data.to_ytdl_dict()

        if obj_type == "playlist":
            if process:
                data = await self.get_playlist_object_complete(spotify_id)
                data.origin_url = spotify_url
                return data.to_ytdl_dict()
            data = await self.get_playlist_object(spotify_id)
            data.origin_url = spotify_url
            return data.to_ytdl_dict()

        return {}

    async def get_track_object(self, track_id: str) -> SpotifyTrack:
        """Lookup a spotify track by its ID and return a SpotifyTrack object"""
        data = await self.get_track(track_id)
        return SpotifyTrack(data)

    async def get_track(self, track_id: str) -> Dict[str, Any]:
        """Get a track's info from its Spotify ID"""
        return await self.make_api_req(f"tracks/{track_id}")

    async def get_album_object_complete(self, album_id: str) -> SpotifyAlbum:
        """Fetch a playlist and all its tracks from Spotify API, returned as a SpotifyAlbum object."""
        aldata = await self.get_album(album_id)
        tracks = aldata.get("tracks", {}).get("items", [])
        next_url = aldata.get("tracks", {}).get("next", None)

        total_tracks = aldata["tracks"]["total"]  # total tracks in playlist.
        log.debug(
            "Spotify Album total tacks:  %(total)s  Next URL: %(url)s",
            {"total": total_tracks, "url": next_url},
        )
        while True:
            if next_url:
                log.debug("Getting Spotify Album Next URL:  %s", next_url)
                next_data = await self.make_api_req(self.api_safe_url(next_url))
                next_tracks = next_data.get("items", None)
                if next_tracks:
                    tracks.extend(next_tracks)
                next_url = next_data.get("next", None)
                continue
            break

        if total_tracks > len(tracks):
            log.warning(
                "Spotify Album Object may not be complete, expected %(total)s tracks but got %(number)s",
                {"total": total_tracks, "number": len(tracks)},
            )
        elif total_tracks < len(tracks):
            log.warning("Spotify Album has more tracks than initial total.")

        aldata["tracks"]["items"] = tracks

        return SpotifyAlbum(aldata)

    async def get_album_object(self, album_id: str) -> SpotifyAlbum:
        """Lookup a spotify playlist by its ID and return a SpotifyAlbum object"""
        data = await self.get_album(album_id)
        return SpotifyAlbum(data)

    async def get_album(self, album_id: str) -> Dict[str, Any]:
        """Get an album's info from its Spotify ID"""
        return await self.make_api_req(f"albums/{album_id}")

    async def get_playlist_object_complete(self, list_id: str) -> SpotifyPlaylist:
        """Fetch a playlist and all its tracks from Spotify API, returned as a SpotifyPlaylist object."""
        pldata = await self.get_playlist(list_id)
        tracks = pldata.get("tracks", {}).get("items", [])
        next_url = pldata.get("tracks", {}).get("next", None)

        total_tracks = pldata["tracks"]["total"]  # total tracks in playlist.
        log.debug(
            "Spotify Playlist total tacks: %(total)s  Next URL: %(url)s",
            {"total": total_tracks, "url": next_url},
        )
        while True:
            if next_url:
                log.debug("Getting Spotify Playlist Next URL:  %s", next_url)
                next_data = await self.make_api_req(self.api_safe_url(next_url))
                next_tracks = next_data.get("items", None)
                if next_tracks:
                    tracks.extend(next_tracks)
                next_url = next_data.get("next", None)
                continue
            break

        if total_tracks > len(tracks):
            log.warning(
                "Spotify Playlist Object may not be complete, expected %(total)s tracks but got %(number)s",
                {"total": total_tracks, "number": len(tracks)},
            )
        elif total_tracks < len(tracks):
            log.warning("Spotify Playlist has more tracks than initial total.")

        pldata["tracks"]["items"] = tracks

        plobj = SpotifyPlaylist(pldata)
        log.debug("Spotify Playlist contained %s usable tracks.", plobj.tracks_loaded)
        return plobj

    async def get_playlist_object(self, list_id: str) -> SpotifyPlaylist:
        """Lookup a spotify playlist by its ID and return a SpotifyPlaylist object"""
        data = await self.get_playlist(list_id)
        return SpotifyPlaylist(data)

    async def get_playlist(self, list_id: str) -> Dict[str, Any]:
        """Get a playlist's info from its Spotify ID"""
        return await self.make_api_req(f"playlists/{list_id}")

    async def make_api_req(self, endpoint: str) -> Dict[str, Any]:
        """Proxy method for making a Spotify request using the correct Auth headers"""
        url = self.API_BASE + endpoint
        token = await self._get_token()
        return await self._make_get(url, headers={"Authorization": f"Bearer {token}"})

    async def _make_get(
        self, url: str, headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Makes a GET request and returns the results"""
        try:
            async with self.aiosession.get(url, headers=headers) as r:
                if r.status != 200:
                    raise SpotifyError(
                        "Response status is not OK: [%(status)s] %(reason)s",
                        fmt_args={"status": r.status, "reason": r.reason},
                    )
                # log.everything("Spotify API GET:  %s\nData:  %s", url, await r.text() )
                data = await r.json()  # type: Dict[str, Any]
                if not isinstance(data, dict):
                    raise SpotifyError("Response JSON did not decode to a dict!")

                return data
        except (
            aiohttp.ClientError,
            aiohttp.ContentTypeError,
            JSONDecodeError,
            SpotifyError,
        ) as e:
            log.exception("Failed making GET request to url:  %s", url)
            if isinstance(e, SpotifyError):
                error = _L(e.message) % e.fmt_args
            else:
                error = str(e)
            raise SpotifyError(
                "Could not make GET to URL:  %(url)s  Reason:  %(raw_error)s",
                fmt_args={"url": url, "raw_error": error},
            ) from e

    async def _make_post(
        self,
        url: str,
        payload: Dict[str, str],
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Makes a POST request and returns the results"""
        try:
            async with self.aiosession.post(url, data=payload, headers=headers) as r:
                if r.status != 200:
                    raise SpotifyError(
                        "Response status is not OK: [%(status)s] %(reason)s",
                        fmt_args={"status": r.status, "reason": r.reason},
                    )

                data = await r.json()  # type: Dict[str, Any]
                if not isinstance(data, dict):
                    raise SpotifyError("Response JSON did not decode to a dict!")

                return data
        except (
            aiohttp.ClientError,
            aiohttp.ContentTypeError,
            JSONDecodeError,
            SpotifyError,
        ) as e:
            log.exception("Failed making POST request to url:  %s", url)
            if isinstance(e, SpotifyError):
                error = _L(e.message) % e.fmt_args
            else:
                error = str(e)
            raise SpotifyError(
                "Could not make POST to URL:  %(url)s  Reason:  %(raw_error)s",
                fmt_args={"url": url, "raw_error": error},
            ) from e

    def _make_token_auth(self, client_id: str, client_secret: str) -> Dict[str, Any]:
        """
        Create a dictionary with suitable Authorization header for HTTP request.
        """
        auth_header = base64.b64encode(
            f"{client_id}:{client_secret}".encode("ascii")
        ).decode("ascii")
        return {"Authorization": f"Basic {auth_header}"}

    def _is_token_valid(self) -> bool:
        """Checks if the token is valid"""
        if not self._token:
            return False
        return int(self._token["expires_at"]) - int(time.time()) > 60

    async def has_token(self) -> bool:
        """Attempt to get token and return True if successful."""
        if await self._get_token():
            return True
        return False

    async def _get_token(self) -> str:
        """Gets the token or creates a new one if expired"""
        if self._is_token_valid() and self._token:
            return str(self._token["access_token"])

        if self.guest_mode:
            token = await self._request_guest_token()
            if not token:
                raise SpotifyError(
                    "Failed to get a guest token from Spotify, please try specifying client ID and client secret"
                )
            try:
                self._token = {
                    "access_token": token["accessToken"],
                    "expires_at": int(token["accessTokenExpirationTimestampMs"]) / 1000,
                }
                log.debug("Created a new Guest Mode access token.")
            except KeyError as e:
                self._token = None
                raise SpotifyError(
                    "API response did not contain the expected data. Missing key: %(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e
            except (ValueError, TypeError) as e:
                self._token = None
                raise SpotifyError(
                    "API response contained unexpected data.\n%(raw_error)s",
                    fmt_args={"raw_error": e},
                ) from e
        else:
            token = await self._request_token()
            if token is None:
                raise SpotifyError(
                    "Requested a token from Spotify, did not end up getting one"
                )
            token["expires_at"] = int(time.time()) + token["expires_in"]
            self._token = token
            log.debug("Created a new Client Mode access token.")
        return str(self._token["access_token"])

    async def _request_token(self) -> Dict[str, Any]:
        """Obtains a token from Spotify and returns it"""
        try:
            payload = {"grant_type": "client_credentials"}
            headers = self._make_token_auth(self.client_id, self.client_secret)
            r = await self._make_post(
                self.OAUTH_TOKEN_URL, payload=payload, headers=headers
            )
            return r
        except asyncio.exceptions.CancelledError as e:  # see request_guest_token()
            if self.max_token_tries == 0:
                raise e

            self.max_token_tries -= 1
            return await self._request_token()

    async def _request_guest_token(self) -> Dict[str, Any]:
        """Obtains a web player token from Spotify and returns it"""
        try:
            async with self.aiosession.get(self.WEB_TOKEN_URL) as r:
                if r.status != 200:
                    # Note:  when status == 429 we could check for "Retry*" headers.
                    # however, this isn't an API endpoint, so we don't get Retry data.
                    raise SpotifyError(
                        "API response status is not OK: [%(status)s]  %(reason)s",
                        fmt_args={"status": r.status, "reason": r.reason},
                    )

                data = await r.json()  # type: Dict[str, Any]
                if not isinstance(data, dict):
                    raise SpotifyError("Response JSON did not decode to a dict!")

                return data
        except (
            aiohttp.ClientError,
            aiohttp.ContentTypeError,
            JSONDecodeError,
            SpotifyError,
        ) as e:
            if log.getEffectiveLevel() <= logging.DEBUG:
                log.exception("Failed to get Spotify Guest Token.")
            else:
                if isinstance(e, SpotifyError):
                    error = _L(e.message) % e.fmt_args
                else:
                    error = str(e)
                log.error(
                    "Failed to get Guest Token due to: %(raw_error)s",
                    {"raw_error": error},
                )
            return {}
import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Generator, List

import discord

from .constructs import Response
from .exceptions import CommandError
from .utils import _func_

if TYPE_CHECKING:
    from .bot import MusicBot

log = logging.getLogger(__name__)

# Mask these to prevent these strings from being extracted by gettext.
TestCommandError = CommandError
loginfo = log.info


class CmdTest:
    def __init__(self, cmd: str, cases: List[str]) -> None:
        """Represents command test cases."""
        self.cmd = cmd
        self.cases = cases

    def __len__(self) -> int:
        return len(self.cases)

    def __str__(self) -> str:
        return self.cmd

    def command_cases(self, prefix: str) -> Generator[str, str, None]:
        """Yields complete command strings which can be sent as a message."""
        for case in self.cases:
            cmd = f"{prefix}{self.cmd} {case}"
            yield cmd


PLAYABLE_STRING_ARRAY = [
    # pointedly empty, do not remove.
    "",
    # HUGE playlist with big files and streams.
    # "https://www.youtube.com/playlist?list=PLBcHt8htZXKVCzW_Mkn4NrByBxn53o3cA",
    # playlist with several tracks.
    # "https://www.youtube.com/playlist?list=PL80gRr4GwcsznLYH-G_FXnzkP5_cHl-KR",
    # playlist with few tracks
    "https://www.youtube.com/playlist?list=PL42rXizBzbC25pvGACvkUQ8EtZcm30BlF",
    # Video link, with playlist ID in URL.
    "https://www.youtube.com/watch?v=bm48ncbhU10&list=PL80gRr4GwcsznLYH-G_FXnzkP5_cHl-KR",
    # Video link
    "https://www.youtube.com/watch?v=bm48ncbhU10",
    # Shorthand video link
    "https://youtu.be/L5uV3gmOH9g",
    # Shorthand with playlist ID
    "https://youtu.be/E3xbLcTj_bs?list=PLTxsp5i8fQO51pAymuKRfkmL4GnPRa6iC",
    # Spotify links
    # TODO: find smaller playlist on spotify
    # "https://open.spotify.com/playlist/37i9dQZF1DXaImRpG7HXqp",
    "https://open.spotify.com/track/0YupMLYOYz6lZDbN3kRt7A?si=5b0eeb51b04c4af9",
    # one item and multi-item albums
    "https://open.spotify.com/album/1y8Yw0NDcP2qxbZufIXt7u",
    "https://open.spotify.com/album/5LbHbwejgZXRZAgzVAjkhj",
    # soundcloud track and set/playlist
    "https://soundcloud.com/neilcic/cabinet-man",
    "https://soundcloud.com/grweston/sets/mashups",
    # bandcamp album
    "https://lemondemon.bandcamp.com/album/spirit-phone",
    # naked search query.
    "slippery people talking heads live 84",
    # search handler format in query.
    "ytsearch4:talking heads stop making sense",
    # generic extractor, static file with no service/meta data
    "https://cdn.discordapp.com/attachments/741945274901200897/875075008723046410/cheesed.mp4",
    # live stream public radio station.
    "https://playerservices.streamtheworld.com/api/livestream-redirect/KUPDFM.mp3?dist=hubbard&source=hubbard-web&ttag=web&gdpr=0",
    # TODO: insert some live streams from youtube and twitch here.
]


TESTRIG_TEST_CASES: List[CmdTest] = [
    # Help command is added to this list at test-start.
    CmdTest("summon", [""]),
    CmdTest("play", PLAYABLE_STRING_ARRAY),
    CmdTest("playnext", PLAYABLE_STRING_ARRAY),
    CmdTest("shuffleplay", PLAYABLE_STRING_ARRAY),
    CmdTest("playnow", PLAYABLE_STRING_ARRAY),
    CmdTest("stream", PLAYABLE_STRING_ARRAY),
    CmdTest("pldump", PLAYABLE_STRING_ARRAY),
    CmdTest(
        "search",
        [
            "",
            "yt 1 test",
            "yt 4 test",
            "yt 10 test",
            "yh 2 test",
            "sc 2 test",
            "'quoted text for reasons'",
            "Who's line is it anyway?",
            "ytsearch4: something about this feels wrong.",
        ],
    ),
    CmdTest("seek", ["", "+30", "-20", "1:01", "61", "nein"]),
    CmdTest("speed", ["", "1", "1.", "1.1", "six", "-0.3", "40"]),
    CmdTest("move", ["", "2 4", "-1 -2", "x y"]),
    CmdTest("remove", ["", "5", "a"]),
    CmdTest("skip", [""]),
    CmdTest("pause", [""]),
    CmdTest("resume", [""]),
    CmdTest("id", [""]),
    CmdTest("queue", [""]),
    CmdTest("np", [""]),
    CmdTest(
        "repeat",
        [
            "",
            "all",
            "playlist",
            "song",
            "on",
            "off",
            "off",
            "off",
        ],
    ),
    CmdTest(
        "cache",
        [
            "",
            "info",
            "clear",
            "update",
        ],
    ),
    CmdTest(
        "volume",
        [
            "",
            "15",
            "15",
            "40",
            "15",
            "x",
            "-1",
            "+4",
        ],
    ),
    CmdTest("shuffle", [""]),
    CmdTest("perms", [""]),
    CmdTest("listids", [""]),
    CmdTest("clear", [""]),
    CmdTest(
        "clean",
        [
            "",
            "4",
            "50",
            "100",
            "1000",
            "-3",
        ],
    ),
    CmdTest("disconnect", [""]),
    CmdTest("id", ["", "TheFae"]),
    CmdTest("joinserver", [""]),
    CmdTest("karaoke", [""]),
    CmdTest("play", ["life during wartime live 84"]),
    CmdTest("karaoke", [""]),
    CmdTest(
        "autoplaylist",
        [
            "",
            "+",  # add current playing
            "-",  # remove current playing
            "+ https://www.youtube.com/playlist?list=PL80gRr4GwcsznLYH-G_FXnzkP5_cHl-KR",
            "+ https://www.youtube.com/watch?v=bm48ncbhU10&list=PL80gRr4GwcsznLYH-G_FXnzkP5_cHl-KR",
            "+ https://www.youtube.com/watch?v=bm48ncbhU10",
            "- https://www.youtube.com/playlist?list=PL80gRr4GwcsznLYH-G_FXnzkP5_cHl-KR",
            "- https://www.youtube.com/watch?v=bm48ncbhU10&list=PL80gRr4GwcsznLYH-G_FXnzkP5_cHl-KR",
            "- https://www.youtube.com/watch?v=bm48ncbhU10",
            "- https://www.youtube.com/watch?v=bm48ncbhU10",
            "https://www.youtube.com/watch?v=bm48ncbhU10",
            "show",
            "set test.txt",
            "+ https://test.url/",
            "- https://test.url/",
            "set default",
        ],
    ),
    CmdTest(
        "blockuser",
        [
            "",
            "+ @MovieBotTest#5179",
            "- @MovieBotTest#5179",
            "- @MovieBotTest#5179",
            "add @MovieBotTest#5179",
            "add @MovieBotTest#5179",
            "remove @MovieBotTest#5179",
        ],
    ),
    CmdTest(
        "blocksong",
        [
            "",
            "+ test text",
            "- test text",
            "- test text",
            "add test text",
            "add test text",
            "remove test text",
        ],
    ),
    CmdTest("resetplaylist", [""]),
    CmdTest("option", ["", "autoplaylist on"]),
    CmdTest("follow", ["", ""]),
    CmdTest("uptime", [""]),
    CmdTest("latency", [""]),
    CmdTest("botversion", [""]),
    #
    # Commands that need owner / perms
    CmdTest("botlatency", [""]),
    CmdTest("checkupdates", [""]),
    CmdTest("setprefix", ["", "**", "**", "?"]),
    CmdTest("setavatar", ["", "https://cdn.imgchest.com/files/6yxkcjrkqg7.png"]),
    CmdTest("setname", ["", f"TB-name-{uuid.uuid4().hex[0:7]}"]),
    CmdTest("setnick", ["", f"TB-nick-{uuid.uuid4().hex[0:7]}"]),
    CmdTest("language", ["", "show", "set", "set xx", "reset"]),
    CmdTest(
        "setalias",
        [
            "",
            "load",
            "add",
            "remove",
            "remove testalias1",
            "add testalias1 help setalias",
            "add testalias1 help setalias",
            "add testalias1 help setprefix",
            "save",
            "remove testalias1",
            "load",
            "remove testalias1",
            "save",
        ],
    ),
    # TODO: need to come up with something to create attachments...
    CmdTest("setcookies", ["", "on", "off"]),
    CmdTest(
        "setperms",
        [
            "",
            "list",
            "reload",
            "help",
            "help CommandWhitelist",
            "show Default CommandWhitelist",
            "add TestGroup1",
            "add TestGroup1",
            "save TestGroup1",
            "remove TestGroup1",
            "remove TestGroup1",
            "reload",
            "set TestGroup1 MaxSongs 200",
            "show TestGroup1 MaxSongs",
            "remove TestGroup1",
            "save",
        ],
    ),
    CmdTest(
        "config",
        [
            "",
            "missing",
            "list",
            "reload",
            "help",
            "help Credentials Token",
            "help MusicBot DefaultVolume",
            "help DefaultVolume",
            "show",
            "show MusicBot DefaultVolume",
            "show DefaultVolume",
            "set MusicBot DefaultVolume 0",
            "set DefaultVolume 100",
            "set MusicBot DefaultVolume 1",
            "diff",
            "save MusicBot DefaultVolume",
            "save DefaultVolume",
            "set MusicBot DefaultVolume .25",
            "set MusicBot DefaultVolume 0.25",
            "reset MusicBot DefaultVolume",
            "reset DefaultVolume",
            "save DefaultVolume",
        ],
    ),
]

"""
Cannot test:
  leaveserver, restart, shutdown
"""


async def run_cmd_tests(
    bot: "MusicBot",
    message: discord.Message,
    command_list: List[str],
    dry: bool = False,
) -> None:
    """
    Handles actually running the command test cases, or reporting data about them.

    :param: bot:  A reference to MusicBot.

    :param: message:  A message, typically the message sent to !testready.

    :param: command_list:  List of existing commands, generated by MusicBot for detecting missing command tests.
                            Note that dev_only commands are excluded.

    :param: dry:  A flag to simply report data about test cases but run no tests.

    :raises:  CommandError if tests are already running.
    """
    # use lock to prevent parallel testing.
    if bot.aiolocks[_func_()].locked():
        raise TestCommandError("Command Tests are already running!")

    async with bot.aiolocks[_func_()]:
        loginfo("Starting Command Tests...")
        start_time = time.time()
        # create a list of help commands to run using input command list and custom tests.
        help_cmd_list = ["", "-missing-", "all"] + command_list
        test_cases = [CmdTest("help", help_cmd_list)] + TESTRIG_TEST_CASES
        test_cmds = [x.cmd for x in test_cases]

        # check for missing tests.
        cmds_missing = []
        for cmd in command_list:
            if cmd not in test_cmds:
                cmds_missing.append(cmd)

        if cmds_missing:
            await bot.safe_send_message(
                message.channel,
                Response(
                    f"\n**Missing Command Cases:**\n```\n{', '.join(cmds_missing)}```",
                    delete_after=120,
                ),
            )

        # a better idea would be buffering messages into a queue to inspect them.
        # but i'm just gonna do this manually for now.
        sleep_time = 2
        cmd_total = 0
        for tc in test_cases:
            cmd_total += len(tc)

        est_time = (sleep_time + 1) * cmd_total

        await bot.safe_send_message(
            message.channel,
            Response(
                f"Total Test Cases:  {cmd_total}\nEstimated Run Time:  {est_time}",
                delete_after=60,
            ),
        )

        if dry:
            return None

        counter = 0
        for test in test_cases:
            for cmd in test.command_cases(""):

                counter += 1
                if message.channel.guild:
                    prefix = bot.server_data[message.channel.guild.id].command_prefix
                else:
                    prefix = bot.config.command_prefix

                cmd = f"{prefix}{cmd}"

                loginfo(
                    "- Sending CMD %(n)s of %(t)s:  %(cmd)s",
                    {"n": counter, "t": cmd_total, "cmd": cmd},
                )

                message.content = cmd
                await bot.on_message(message)
                await asyncio.sleep(sleep_time)

        print("Done. Finally....")
        t = time.time() - start_time
        print(f"Took {t:.3f} seconds.")
import datetime
import inspect
import logging
import pathlib
import re
import unicodedata
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    TypeVar,
    Union,
)

from .constants import DISCORD_MSG_CHAR_LIMIT
from .exceptions import PermissionsError

if TYPE_CHECKING:
    from discord import Member, StageChannel, VoiceChannel

    from .bot import MusicBot

CmdFunc = TypeVar("CmdFunc", bound=Callable[..., Any])

log = logging.getLogger(__name__)


def load_file(
    filename: pathlib.Path, skip_commented_lines: bool = True, comment_char: str = "#"
) -> List[str]:
    """
    Read `filename` into list of strings but ignore lines starting
    with the given `comment_char` character.
    Default comment character is #
    """
    try:
        with open(filename, encoding="utf8") as f:
            results = []
            for line in f:
                line = line.strip()

                if line and not (
                    skip_commented_lines and line.startswith(comment_char)
                ):
                    results.append(line)

            return results

    except IOError as e:
        print("Error loading", filename, e)
        return []


def write_file(filename: pathlib.Path, contents: Iterable[str]) -> None:
    """
    Open the given `filename` for writing in utf8 and write each item in
    `contents` to the file as a single line.
    Shorthand function that is now outmoded by pathlib, and could/should be replaced.
    """
    with open(filename, "w", encoding="utf8") as f:
        for item in contents:
            f.write(str(item))
            f.write("\n")


def slugify(value: str, allow_unicode: bool = False) -> str:
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't letters, numbers,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing spaces, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


def paginate(
    content: Union[str, List[str]],
    *,
    length: int = DISCORD_MSG_CHAR_LIMIT,
    reserve: int = 0,
) -> List[str]:
    """
    Split up a large string or list of strings into chunks for sending to discord.
    """
    if isinstance(content, str):
        contentlist = content.split("\n")
    elif isinstance(content, list):
        contentlist = content
    else:
        raise ValueError(f"Content must be str or list, not {type(content)}")

    chunks = []
    currentchunk = ""

    for line in contentlist:
        if len(currentchunk) + len(line) < length - reserve:
            currentchunk += line + "\n"
        else:
            chunks.append(currentchunk)
            currentchunk = ""

    if currentchunk:
        chunks.append(currentchunk)

    return chunks


def _func_() -> str:
    """
    Gets the name of the calling frame code object.
    Emulates __func__ from C++
    """
    frame = inspect.currentframe()
    if not frame or not frame.f_back:
        raise RuntimeError(
            "Call to _func_() failed, may not be available in this context."
        )

    return frame.f_back.f_code.co_name


def _get_variable(name: str) -> Any:
    """
    Inspect each frame in the call stack for local variables with the
    `name` given then return that variable's value or None if not found.
    """
    stack = inspect.stack()
    try:
        for frames in stack:
            try:
                frame = frames[0]
                current_locals = frame.f_locals
                if name in current_locals:
                    return current_locals[name]
            finally:
                del frame
    finally:
        del stack

    return None


def owner_only(func: Callable[..., Any]) -> Any:
    """
    Decorator function that checks the invoking message author ID matches
    the Owner ID which MusicBot has determined either via Config or
    Discord AppInfo.
    """

    @wraps(func)
    async def wrapper(self: "MusicBot", *args: Any, **kwargs: Any) -> Any:
        # Only allow the owner to use these commands
        orig_msg = _get_variable("message")

        if not orig_msg or orig_msg.author.id == self.config.owner_id:
            return await func(self, *args, **kwargs)
        raise PermissionsError("Only the owner can use this command.")

    setattr(wrapper, "admin_only", True)
    return wrapper


def dev_only(func: Callable[..., Any]) -> Any:
    """
    Decorator function that sets `dev_cmd` as an attribute to the function
    it decorates.
    This is then checked in MusicBot.on_message to ensure the protected
    commands are not executed by non "dev" users.
    """

    @wraps(func)
    async def wrapper(self: "MusicBot", *args: Any, **kwargs: Any) -> Any:
        orig_msg = _get_variable("message")

        if orig_msg.author.id in self.config.dev_ids:
            return await func(self, *args, **kwargs)
        raise PermissionsError("Only dev users can use this command.")

    setattr(wrapper, "dev_cmd", True)
    return wrapper


def command_helper(
    usage: Optional[List[str]] = None,
    desc: str = "",
    remap_subs: Optional[Dict[str, str]] = None,
    allow_dm: bool = False,
) -> Callable[[CmdFunc], CmdFunc]:
    """
    Decorator which enables command help to be translated and retires the doc-block.
    The usage strings are filtered and will replace "{cmd}" with "{prefix}cmd_name" where
    {prefix} is replaced only while formatting help for display.
    Filtered usage should reduce typos when writing usage strings. :)

    Usage command parameters should adhear to these rules:
    1. All literal parameters must be lower case and alphanumeric.
    2. All placeholder parameters must be upper case and alphanumeric.
    3. < > denotes a required parameter.
    4. [ ] denotes an optional parameter.
    5.  |  denotes multiple choices for the parameter.
    6. Literal terms may appear without parameter marks.

    :param: usage:  A list of usage patterns with descriptions.
                    If omitted, will default to the prefix and command name alone.
                    Set to an empty list if you want no usage examples.

    :param: desc:   A general description of the command.

    :param: remap_subs:  A dictionary for normalizing alternate sub-commands into a standard sub-command.
                         This allows users to simplify permissions for these commands.
                         It should be avoided for all new commands, deprecated and reserved for backwards compat.
                         Ex:  {"alt": "standard"}

    :param: allow_dm:  Allow the command to be used in DM.
                       This wont work for commands that need guild data.
    """
    if usage is None:
        usage = ["{cmd}"]

    def remap_subcommands(args: List[str]) -> List[str]:
        """Remaps the first argument in the list according to an external map."""
        if not remap_subs or not args:
            return args
        if args[0] in remap_subs.keys():
            args[0] = remap_subs[args[0]]
            return args
        return args

    def deco(func: Callable[..., Any]) -> Any:
        u = [
            u.replace("{cmd}", f"{{prefix}}{func.__name__.replace('cmd_', '')}")
            for u in usage
        ]

        @wraps(func)
        async def wrapper(self: "MusicBot", *args: Any, **kwargs: Any) -> Any:
            return await func(self, *args, **kwargs)

        setattr(wrapper, "help_usage", u)
        setattr(wrapper, "help_desc", desc)
        setattr(wrapper, "remap_subcommands", remap_subcommands)
        setattr(wrapper, "cmd_in_dm", allow_dm)
        return wrapper

    return deco


def is_empty_voice_channel(  # pylint: disable=dangerous-default-value
    voice_channel: Union["VoiceChannel", "StageChannel", None],
    *,
    exclude_me: bool = True,
    exclude_deaf: bool = True,
    include_bots: Set[int] = set(),
) -> bool:
    """
    Check if the given `voice_channel` is figuratively or literally empty.

    :param: `exclude_me`: Exclude our bot instance, the default.
    :param: `exclude_deaf`: Excludes members who are self-deaf or server-deaf.
    :param: `include_bots`: A list of bot IDs to include if they are present.
    """
    if not voice_channel:
        log.debug("Cannot count members when voice_channel is None.")
        return True

    def _check(member: "Member") -> bool:
        if exclude_me and member == voice_channel.guild.me:
            return False

        if (
            member.voice
            and exclude_deaf
            and any([member.voice.deaf, member.voice.self_deaf])
        ):
            return False

        if member.bot and member.id not in include_bots:
            return False

        return True

    return not sum(1 for m in voice_channel.members if _check(m))


def count_members_in_voice(  # pylint: disable=dangerous-default-value
    voice_channel: Union["VoiceChannel", "StageChannel", None],
    include_only: Iterable[int] = [],
    include_bots: Iterable[int] = [],
    exclude_ids: Iterable[int] = [],
    exclude_me: bool = True,
    exclude_deaf: bool = True,
) -> int:
    """
    Counts the number of members in given voice channel.
    By default it excludes all deaf users, all bots, and the MusicBot client itself.

    :param: voice_channel:  A VoiceChannel to inspect.
    :param: include_only:  A list of Member IDs to check for, only members in this list are counted if present.
    :param: include_bots:  A list of Bot Member IDs to include.  By default all bots are excluded.
    :param: exclude_ids:  A list of Member IDs to exclude from the count.
    :param: exclude_me:  A switch to, by default, exclude the bot ClientUser.
    :param: exclude_deaf:  A switch to, by default, exclude members who are deaf.
    """
    if not voice_channel:
        log.debug("Cannot count members when voice_channel is None.")
        return 0

    num_voice = 0
    for member in voice_channel.members:
        if not member:
            continue

        if member.bot and member.id not in include_bots:
            continue

        if exclude_me and member == voice_channel.guild.me:
            continue

        if exclude_ids and member.id in exclude_ids:
            continue

        voice = member.voice
        if not voice:
            continue

        if exclude_deaf and (voice.deaf or voice.self_deaf):
            continue

        if include_only and member.id not in include_only:
            continue

        num_voice += 1
    return num_voice


def format_song_duration(seconds: Union[int, float, datetime.timedelta]) -> str:
    """
    Take in the given `seconds` and format it as a compact timedelta string.
    If input `seconds` is an int or float, it will be converted to a timedelta.
    If the input has partial seconds, those are quietly removed without rounding.
    """
    if isinstance(seconds, (int, float)):
        seconds = datetime.timedelta(seconds=seconds)

    if not isinstance(seconds, datetime.timedelta):
        raise TypeError(
            "Can only format a duration that is int, float, or timedelta object."
        )

    # Simply remove any microseconds from the delta.
    time_delta = str(seconds).split(".", maxsplit=1)[0]
    t_hours = seconds.seconds / 3600

    # if hours is 0 remove it.
    if seconds.days == 0 and t_hours < 1:
        duration_array = time_delta.split(":")
        return ":".join(duration_array[1:])
    return time_delta


def format_size_from_bytes(size_bytes: int) -> str:
    """
    Format a given `size_bytes` into an approximate short-hand notation.
    """
    suffix = {0: "", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    power = 1024
    size = float(size_bytes)
    i = 0
    while size > power:
        size /= power
        i += 1
    return f"{size:.3f} {suffix[i]}B"


def format_size_to_bytes(size_str: str, strict_si: bool = False) -> int:
    """
    Convert human-friendly data-size notation into integer.
    Note: this function is not intended to convert Bits notation.

    :param: size_str:  A size notation like: 20MB or "12.3 kb"
    :param: strict_si:  Toggles use of 1000 rather than 1024 for SI suffixes.
    """
    if not size_str:
        return 0

    si_units = 1024
    if strict_si:
        si_units = 1000
    suffix_list = {
        "kilobyte": si_units,
        "megabyte": si_units**2,
        "gigabyte": si_units**3,
        "terabyte": si_units**4,
        "petabyte": si_units**5,
        "exabyte": si_units**6,
        "zetabyte": si_units**7,
        "yottabyte": si_units**8,
        "kb": si_units,
        "mb": si_units**2,
        "gb": si_units**3,
        "tb": si_units**4,
        "pb": si_units**5,
        "eb": si_units**6,
        "zb": si_units**7,
        "yb": si_units**8,
        "kibibyte": 1024,
        "mebibyte": 1024**2,
        "gibibyte": 1024**3,
        "tebibyte": 1024**4,
        "pebibyte": 1024**5,
        "exbibyte": 1024**6,
        "zebibyte": 1024**7,
        "yobibyte": 1024**8,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
        "pib": 1024**5,
        "eib": 1024**6,
        "zib": 1024**7,
        "yib": 1024**8,
    }
    size_str = size_str.lower().strip().strip("s")
    for suffix, conversion in suffix_list.items():
        if size_str.endswith(suffix):
            return int(float(size_str[0 : -len(suffix)]) * conversion)

    if size_str.endswith("b"):
        size_str = size_str[0:-1]
    elif size_str.endswith("byte"):
        size_str = size_str[0:-4]

    return int(float(size_str))


def format_time_to_seconds(time_str: Union[str, int]) -> int:
    """
    Convert a phrase containing time duration(s) to seconds as int
    This function allows for interesting/sloppy time notations like:
    - 1yearand2seconds  = 31556954
    - 8s 1d             = 86408
    - .5 hours          = 1800
    - 99 + 1            = 100
    - 3600              = 3600
    Only partial seconds are not supported, thus ".5s + 1.5s" will be 1 not 2.

    :param: time_str:  is assumed to contain a time duration as str or int.

    :returns:  0 if no time value is recognized, rather than raise a ValueError.
    """
    if isinstance(time_str, int):
        return time_str

    # support HH:MM:SS notations like those from timedelta.__str__
    hms_total = 0
    if ":" in time_str:
        parts = time_str.split()
        for part in parts:
            bits = part.split(":")
            part_sec = 0
            try:
                # format is MM:SS
                if len(bits) == 2:
                    m = int(bits[0])
                    s = int(bits[1])
                    part_sec += (m * 60) + s
                # format is HH:MM:SS
                elif len(bits) == 3:
                    h = int(bits[0] or 0)
                    m = int(bits[1])
                    s = int(bits[2] or 0)
                    part_sec += (h * 3600) + (m * 60) + s
                # format is not supported.
                else:
                    continue
                hms_total += part_sec
                time_str = time_str.replace(part, "")
            except (ValueError, TypeError):
                continue

    # TODO: find a good way to make this i18n friendly.
    time_lex = re.compile(r"(\d*\.?\d+)\s*(y|d|h|m|s)?", re.I)
    unit_seconds = {
        "y": 31556952,
        "d": 86400,
        "h": 3600,
        "m": 60,
        "s": 1,
    }
    total_sec = hms_total
    for value, unit in time_lex.findall(time_str):
        if not unit:
            unit = "s"
        else:
            unit = unit[0].lower().strip()
        total_sec += int(float(value) * unit_seconds[unit])
    return total_sec
"""
 ytdlp_oauth2_plugin contains code provided under an Unlicense license,
 based on the plugin found here:
   https://github.com/coletdjnz/yt-dlp-youtube-oauth2

 It is modified by MusicBot contributors to better integrate features.
 It may not contain all features or updates, and may break at any time.
 It will be replaced with the original plugin if it is installed.
"""

import datetime
import importlib
import inspect
import json
import logging
import pathlib
import time
import urllib.parse
import uuid
from typing import TYPE_CHECKING, Any, Dict, Tuple

import yt_dlp.networking  # type: ignore[import-untyped]
from yt_dlp.extractor.common import InfoExtractor  # type: ignore[import-untyped]
from yt_dlp.extractor.youtube import (  # type: ignore[import-untyped]
    YoutubeBaseInfoExtractor,
)
from yt_dlp.utils.traversal import traverse_obj  # type: ignore[import-untyped]

from . import write_path
from .constants import (
    DATA_FILE_YTDLP_OAUTH2,
    DEFAULT_DATA_DIR,
    DEFAULT_YTDLP_OAUTH2_SCOPES,
    DEFAULT_YTDLP_OAUTH2_TTL,
    YTDLP_OAUTH2_CLIENTS,
    YTDLP_OAUTH2_EXCLUDED_IES,
    YTDLP_OAUTH2_UNSUPPORTED_CLIENTS,
)

if TYPE_CHECKING:
    from .config import Config

TokenDict = Dict[str, Any]

log = logging.getLogger(__name__)


class YtdlpOAuth2Exception(Exception):
    pass


class YouTubeOAuth2Handler(InfoExtractor):  # type: ignore[misc]
    # pylint: disable=W0223
    _oauth2_token_path: pathlib.Path = write_path(DEFAULT_DATA_DIR).joinpath(
        DATA_FILE_YTDLP_OAUTH2
    )
    _client_token_data: TokenDict = {}
    _client_id: str = ""
    # I hate this, I am stupid and lazy. Future me/you, sorry and thanks ahead of time. :)
    _client_secret: str = ""
    _client_scopes: str = DEFAULT_YTDLP_OAUTH2_SCOPES

    @staticmethod
    def set_client_id(client_id: str) -> None:
        """
        Sets the shared, static client ID for use by OAuth2.
        """
        YouTubeOAuth2Handler._client_id = client_id

    @staticmethod
    def set_client_secret(client_secret: str) -> None:
        """
        Sets the shared, static client secret for use by OAuth2.
        """
        YouTubeOAuth2Handler._client_secret = client_secret

    def _save_token_data(self, token_data: TokenDict) -> None:
        """
        Handles saving token data as JSON to file system.
        """
        try:
            with open(self._oauth2_token_path, "w", encoding="utf8") as fh:
                json.dump(token_data, fh)
        except (OSError, TypeError) as e:
            log.error("Failed to save ytdlp oauth2 token data due to:  %s", e)

    def _load_token_data(self) -> TokenDict:
        """
        Handles loading token data as JSON from file system.
        """
        log.everything(  # type: ignore[attr-defined]
            "Loading YouTube TV OAuth2 token data."
        )
        d: TokenDict = {}
        if not self._oauth2_token_path.is_file():
            return d

        try:
            with open(self._oauth2_token_path, "r", encoding="utf8") as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            log.error("Failed to load ytdlp oauth2 token data due to:  %s", e)
        return d

    def store_token(self, token_data: TokenDict) -> None:
        """
        Saves token data to cache.
        """
        log.everything(  # type: ignore[attr-defined]
            "Storing YouTube TV OAuth2 token data"
        )
        self._save_token_data(token_data)
        self._client_token_data = token_data

    def get_token(self) -> TokenDict:
        """
        Returns token data from cache.
        """
        if not getattr(self, "_client_token_data", None):
            self._client_token_data = self._load_token_data()

        return self._client_token_data

    def validate_token_data(self, token_data: TokenDict) -> bool:
        """
        Validate required token data exists.
        """
        return all(
            key in token_data
            for key in ("access_token", "expires", "refresh_token", "token_type")
        )

    def initialize_oauth(self) -> TokenDict:
        """
        Validates existing OAuth2 data or triggers authorization flow.
        """
        token_data = self.get_token()

        if token_data and not self.validate_token_data(token_data):
            log.warning("Invalid cached OAuth2 token data.")
            token_data = {}

        if not token_data:
            token_data = self.authorize()
            self.store_token(token_data)

            if not token_data:
                raise YtdlpOAuth2Exception("Ytdlp OAuth2 failed to fetch token data.")

        if (
            token_data.get("expires", 0)
            < datetime.datetime.now(datetime.timezone.utc).timestamp() + 60
        ):
            log.everything(  # type: ignore[attr-defined]
                "Access token expired, refreshing"
            )
            token_data = self.refresh_token(token_data["refresh_token"])
            self.store_token(token_data)

        return token_data

    def handle_oauth(self, request: yt_dlp.networking.Request) -> None:
        """
        Fix up request to include proper OAuth2 data.
        """
        if not urllib.parse.urlparse(request.url).netloc.endswith("youtube.com"):
            return

        token_data = self.initialize_oauth()
        # These are only require for cookies and interfere with OAuth2
        request.headers.pop("X-Goog-PageId", None)
        request.headers.pop("X-Goog-AuthUser", None)
        # In case user tries to use cookies at the same time
        if "Authorization" in request.headers:
            log.warning(
                "YouTube cookies have been provided, but OAuth2 is being used. "
                "If you encounter problems, stop providing YouTube cookies to yt-dlp."
            )
            request.headers.pop("Authorization", None)
            request.headers.pop("X-Origin", None)

        # Not even used anymore, should be removed from core...
        request.headers.pop("X-Youtube-Identity-Token", None)

        authorization_header = {
            "Authorization": f'{token_data["token_type"]} {token_data["access_token"]}'
        }
        request.headers.update(authorization_header)

    def refresh_token(self, refresh_token: TokenDict) -> TokenDict:
        """
        Refresh authorization using refresh data or restarting auth flow.
        """
        log.info("Refreshing YouTube TV oauth2 token...")
        token_response = self._download_json(
            "https://www.youtube.com/o/oauth2/token",
            video_id="oauth2",
            note="Refreshing OAuth2 Token",
            data=json.dumps(
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode(),
            headers={"Content-Type": "application/json", "__youtube_oauth__": True},
        )
        error = traverse_obj(token_response, "error")
        if error:
            log.warning(
                "Failed to refresh OAuth2 access token due to:  %s\n"
                "Restarting authorization flow...",
                error,
            )
            return self.authorize()

        return {
            "access_token": token_response["access_token"],
            "expires": datetime.datetime.now(datetime.timezone.utc).timestamp()
            + token_response["expires_in"],
            "token_type": token_response["token_type"],
            "refresh_token": token_response.get("refresh_token", refresh_token),
        }

    def authorize(self) -> TokenDict:
        """
        Start authorization flow and loop until authorized or time-out.
        """
        log.everything("Starting oauth2 flow...")  # type: ignore[attr-defined]
        code_response = self._download_json(
            "https://www.youtube.com/o/oauth2/device/code",
            video_id="oauth2",
            note="Initializing OAuth2 Authorization Flow",
            data=json.dumps(
                {
                    "client_id": YouTubeOAuth2Handler._client_id,
                    "scope": YouTubeOAuth2Handler._client_scopes,
                    "device_id": uuid.uuid4().hex,
                    "device_model": "ytlr::",
                }
            ).encode(),
            headers={"Content-Type": "application/json", "__youtube_oauth__": True},
        )

        verification_url = code_response["verification_url"]
        user_code = code_response["user_code"]
        log.info(
            "\nNOTICE:\n"
            "To give yt-dlp access to your account, visit:\n  %s\n"
            "Then enter this authorization code:  %s\n"
            "You have %s seconds to complete authorization.\n",
            verification_url,
            user_code,
            DEFAULT_YTDLP_OAUTH2_TTL,
        )
        log.warning(
            "The application may hang until authorization time out if closed at this point. This is normal."
        )

        ttl = time.time() + DEFAULT_YTDLP_OAUTH2_TTL
        while True:
            if time.time() > ttl:
                log.error("Timed out while waiting for OAuth2 token.")
                raise YtdlpOAuth2Exception(
                    "OAuth2 is enabled but authorization was not given in time.\n"
                    "The owner must authorize YouTube before you can play from it."
                )

            token_response = self._download_json(
                "https://www.youtube.com/o/oauth2/token",
                video_id="oauth2",
                note=False,
                data=json.dumps(
                    {
                        "client_id": YouTubeOAuth2Handler._client_id,
                        "client_secret": YouTubeOAuth2Handler._client_secret,
                        "code": code_response["device_code"],
                        "grant_type": "http://oauth.net/grant_type/device/1.0",
                    }
                ).encode(),
                headers={"Content-Type": "application/json", "__youtube_oauth__": True},
            )

            error = traverse_obj(token_response, "error")
            if error:
                if error == "authorization_pending":
                    time.sleep(code_response["interval"])
                    continue
                if error == "expired_token":
                    log.warning(
                        "The device code has expired, restarting authorization flow for yt-dlp."
                    )
                    return self.authorize()
                raise YtdlpOAuth2Exception(f"Unhandled OAuth2 Error: {error}")

            log.everything(  # type: ignore[attr-defined]
                "Yt-dlp OAuth2 authorization successful."
            )
            return {
                "access_token": token_response["access_token"],
                "expires": datetime.datetime.now(datetime.timezone.utc).timestamp()
                + token_response["expires_in"],
                "refresh_token": token_response["refresh_token"],
                "token_type": token_response["token_type"],
            }


def enable_ytdlp_oauth2_plugin(config: "Config") -> None:
    """
    Controls addition of OAuth2 plugin to ytdlp.
    """
    YouTubeOAuth2Handler.set_client_id(config.ytdlp_oauth2_client_id)
    YouTubeOAuth2Handler.set_client_secret(config.ytdlp_oauth2_client_secret)

    # build a list of info extractors to be patched.
    youtube_extractors = filter(
        lambda m: issubclass(m[1], YoutubeBaseInfoExtractor)
        and m[0] not in YTDLP_OAUTH2_EXCLUDED_IES,
        inspect.getmembers(
            importlib.import_module("yt_dlp.extractor.youtube"), inspect.isclass
        ),
    )

    # patch each of the info extractors.
    for _, ie in youtube_extractors:
        log.everything(  # type: ignore[attr-defined]
            "Adding OAuth2 Plugin to Yt-dlp IE:  %s", ie
        )

        class _YouTubeOAuth(
            ie,  # type: ignore[valid-type, misc]
            YouTubeOAuth2Handler,
            plugin_name="oauth2",  # type: ignore[call-arg]
        ):
            # pylint: disable=W0223,C0103
            _DEFAULT_CLIENTS: Tuple[str]
            _NETRC_MACHINE = "youtube"
            _use_oauth2 = False

            def _perform_login(self, username: str, password: str) -> Any:
                if username == "mb_oauth2":
                    # Ensure clients are supported.
                    self._DEFAULT_CLIENTS = tuple(
                        c
                        for c in getattr(self, "_DEFAULT_CLIENTS", [])
                        if c not in YTDLP_OAUTH2_UNSUPPORTED_CLIENTS
                    ) + tuple(YTDLP_OAUTH2_CLIENTS)
                    log.everything(  # type: ignore[attr-defined]
                        "Default Yt-dlp Clients:  %s", self._DEFAULT_CLIENTS
                    )

                    self._use_oauth2 = True
                    self.initialize_oauth()
                    return None
                return super()._perform_login(username, password)

            def _create_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                request = super()._create_request(*args, **kwargs)
                if "__youtube_oauth__" in request.headers:
                    request.headers.pop("__youtube_oauth__")
                elif self._use_oauth2:
                    self.handle_oauth(request)
                return request

            @property
            def is_authenticated(self) -> bool:
                """Validate oauth2 auth data or return super value."""
                if self._use_oauth2:
                    token_data = self.get_token()
                    if token_data and self.validate_token_data(token_data):
                        return True
                if super().is_authenticated:
                    return True
                return False
