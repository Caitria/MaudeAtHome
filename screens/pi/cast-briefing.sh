#!/bin/bash
# Cast the briefing page to the bedroom display, stop-first (see OPERATIONS.md).
# "Bedroom display" is the display's cast name — CONFIG: use your own.
~/caster/bin/catt -d "Bedroom display" stop >> ~/cast-briefing.log 2>&1
sleep 10
~/caster/bin/catt -d "Bedroom display" cast_site http://CASTPI_LAN_IP:8080/ >> ~/cast-briefing.log 2>&1
