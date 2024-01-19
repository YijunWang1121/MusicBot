import asyncio
import traceback
import collections
from typing import Callable, DefaultDict, Dict, List, Any

EventCallback = Callable[..., Any]
EventList = List[EventCallback]
EventDict = DefaultDict[str, EventList]

class EventEmitter:
    def __init__(self: "EventEmitter") -> None:
        self._events: EventDict = collections.defaultdict(list)
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

    def emit(self, event: str, *args: List[Any], **kwargs: Dict[str, Any]) -> None:
        if event not in self._events:
            return

        for cb in list(self._events[event]):
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.ensure_future(cb(*args, **kwargs), loop=self.loop)
                else:
                    cb(*args, **kwargs)

            except Exception:
                traceback.print_exc()

    def on(self, event: str, cb: EventCallback) -> "EventEmitter":
        self._events[event].append(cb)
        return self

    def off(self, event: str, cb: EventCallback) -> "EventEmitter":
        self._events[event].remove(cb)

        if not self._events[event]:
            del self._events[event]

        return self

    def once(self, event: str, cb: EventCallback) -> "EventEmitter":
        def callback(*args: List[Any], **kwargs: Dict[str, Any]) -> Any:
            self.off(event, callback)
            return cb(*args, **kwargs)

        return self.on(event, callback)
