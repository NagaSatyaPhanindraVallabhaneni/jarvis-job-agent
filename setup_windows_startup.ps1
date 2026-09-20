# Sets up Jarvis Autonomous Job Agent to start automatically on Windows boot
$TargetDir = "d:\jarvis_job_agent"
$BatchFile = "$TargetDir\run_24_7.bat"
$StartupFolder = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Startup)
$ShortcutPath = "$StartupFolder\JarvisJobAgent24x7.lnk"

$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $BatchFile
$Shortcut.WorkingDirectory = $TargetDir
$Shortcut.Description = "Jarvis Autonomous 24/7 Job Search & Application Agent"
$Shortcut.Save()

Write-Host "===================================================================="
Write-Host "SUCCESS: Jarvis 24/7 Agent registered in Windows Startup!"
Write-Host "Location: $ShortcutPath"
Write-Host "The agent will now launch automatically on every Windows boot/logon."
Write-Host "===================================================================="
