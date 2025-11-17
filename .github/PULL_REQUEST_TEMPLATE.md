<!-- Please replace sections in <> and remove this comment before submitting -->
# Pull Request

## Description
<!-- Describe the change and why it was made -->

## Related issue
- Fixes: <!-- link or issue number, if any -->
- Feat: <!-- add sem6/PES2UG23CS mapping -->

---

## If Contributing / Adding a batch mapping

Update `frontend/web/mapping.json` and open a PR. Use the checklist below and mark each item when completed.

- [ ] Open your browser's Developer Tools (Right-Click → Inspect Element / `F12` / `Ctrl+Shift+I`) and go to the Network tab (show all requests).
- [ ] Sign in to PESUAcademy: https://www.pesuacademy.com/Academy/s/studentProfilePESU
- [ ] Open the attendance page and select your semester.
- [ ] Find and open the request to `/studentProfilePESUAdmin`.
- [ ] In that request, view the Payload/Request (Form Data) and locate an entry like:
	`controllerMode=6407&actionType=8&batchClassId=2660&menuId=660`
- [ ] Note the `batchClassId` value (for example `2660`) — this is the `BATCH_CLASS_ID` key you must add to `frontend/web/mapping.json`.
- [ ] Optionally add `SUBJECT_MAPPING` entries for your subjects in the same file.
- [ ] Save your changes to `frontend/web/mapping.json`.
- [ ] Run `uv run main.py` and try logging in with your SRN/Password.
- [ ] Open a Pull Request (feat: add PES2UG25EC)

Example mapping snippet to add:

```json
"BATCH_CLASS_ID_MAPPING": {
	"PES2UG23AM": 2970
}...
```
