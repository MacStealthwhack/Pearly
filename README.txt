Router setup
* Once Pearly conencts, map it to 192.168.0.56

Computer setup
* Add "192.168.0.56 pearly pearly.local" to the end of C:\Windows\System32\drivers\etc\hosts
* SSH setup commands
  * ssh-keygen -t ed25519 -C "<device> to Pearly"
  * type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh admin@pearly.local "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

Commands
* Copy to pearly: scp .\pearly_app.py admin@pearly.local:~/pearly_app.py