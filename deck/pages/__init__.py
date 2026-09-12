"""Page implementations. Import the class you want, or use build_pages()."""
from .launcher import LauncherPage
from .sysmon import SysMonPage
from .media import MediaPage
from .calendar import CalendarPage
from .zoom import ZoomPage
from .nowplaying import NowPlayingPage

__all__ = ['LauncherPage', 'SysMonPage', 'MediaPage', 'CalendarPage', 'ZoomPage',
           'NowPlayingPage']
