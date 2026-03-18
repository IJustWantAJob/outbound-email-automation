#!/bin/bash
# Import campaign JSON files into the app
# Usage: cd exports && bash import_all.sh
#
# This will:
#   1. Import each campaign (creates Campaign + Contacts + Emails)
#   2. Skip contacts that already exist (idempotent via external_id)
#   3. Campaigns are created in 'draft' status -- activate them in the UI
#
# NOTE: If a campaign with the same name already exists, it will create
# a DUPLICATE campaign. To re-import, first delete the old campaign in the UI.

BASE_URL="${CAMPAIGN_URL:-https://campaign.example.com}"

echo "Importing campaigns to $BASE_URL"
echo "================================="
echo ""

for file in *.json; do
    if [ ! -f "$file" ] || [ "$file" = "*.json" ]; then
        continue
    fi
    echo -n "Importing $file ... "
    RESULT=$(curl -s -X POST "$BASE_URL/api/contacts/import-json" \
        -H "Content-Type: application/json" \
        -d @"$file")
    echo "$RESULT"
    echo ""
done

echo "Done! Go to $BASE_URL/campaigns to activate campaigns."
echo "Then go to $BASE_URL/emails/queue to see the schedule preview."
