@echo off
REM Build a standalone Windows .exe of the playlist downloader.
REM Put ffmpeg.exe in this same folder first if you want it bundled inside the .exe.

pip install -U yt-dlp pyinstaller

set FFARG=
if exist ffmpeg.exe (
    echo Bundling ffmpeg.exe into the exe...
    set FFARG=--add-binary "ffmpeg.exe;."
) else (
    echo ffmpeg.exe not found here - the exe will need ffmpeg next to it or in PATH.
)

pyinstaller --onefile --windowed --clean --name YT-Playlist-Downloader --collect-all yt_dlp %FFARG% yt_playlist_gui.py

echo.
echo Done. Your exe is in the "dist" folder: dist\YT-Playlist-Downloader.exe
pause
