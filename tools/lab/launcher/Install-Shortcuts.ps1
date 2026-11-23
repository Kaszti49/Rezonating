# Put "Rezonating Lab" and "Stop Rezonating Lab" on the desktop and in the Start menu. Run once per machine.
# Remove them by deleting the two shortcuts; nothing else is installed.
$here = $PSScriptRoot
$vbs = Join-Path $here 'start-hidden.vbs'
$icon = Join-Path $here 'rezonating-lab.ico'
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Rezonating'
New-Item -ItemType Directory -Force $menu | Out-Null
foreach ($dir in @($desktop, $menu)) {
    foreach ($item in @(
            @{ Name = 'Rezonating Lab'; Script = 'Start-RezonatingLab.ps1'; Text = 'Start the lab server and open the Lab' },
            @{ Name = 'Stop Rezonating Lab'; Script = 'Stop-RezonatingLab.ps1'; Text = 'Stop the lab server' }
        )) {
        if ($dir -eq $desktop -and $item.Name -like 'Stop*') { continue }  # the desktop gets only the start button
        $lnk = $shell.CreateShortcut((Join-Path $dir "$($item.Name).lnk"))
        $lnk.TargetPath = "$env:SystemRoot\System32\wscript.exe"
        $lnk.Arguments = "`"$vbs`" $($item.Script)"
        $lnk.WorkingDirectory = $here
        $lnk.Description = $item.Text
        if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
        $lnk.Save()
        Write-Host "made $($lnk.FullName)"
    }
}
