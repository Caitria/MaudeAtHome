#!/bin/bash
# Fetch the current briefing edition (hosted as a single Drive file, updated
# in place by the edition routine) and swap it in only if it looks sane.
# CONFIG: YOUR_BRIEFING_FILE_ID = the Drive file ID of your briefing file.
curl -fsSL "https://drive.google.com/uc?export=download&id=YOUR_BRIEFING_FILE_ID" -o /tmp/briefing-new.html && grep -qi "Briefing" /tmp/briefing-new.html && mv /tmp/briefing-new.html ~/briefing/index.html && echo "briefing updated $(date)" >> ~/briefing-fetch.log
