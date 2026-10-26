# eMAG Price Tracker

Checks the eMAG listing for the Bosch WTH8520BBY tumble dryer daily and emails the detected price through the Gmail API.

Product: [Bosch WTH8520BBY on eMAG](https://www.emag.ro/uscator-de-rufe-bosch-pompa-de-caldura-8-kg-15-programe-autodry-technology-antivibration-filtru-easyclean-clasa-d-alb-negru-wth8520bby/pd/DK77M73BM/)

## Schedule

GitHub Actions runs daily at **09:00 UTC** (`0 9 * * *`). This is 11:00 in Romania during winter time (EET, UTC+2) and 12:00 during summer time (EEST, UTC+3). Run manually from **GitHub → Actions → eMAG price check → Run workflow**.

## Configure Gmail API

Open **Settings → Secrets and variables → Actions → New repository secret** and add these five repository secrets:

| Secret | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | Client ID from the dedicated Google OAuth **Web application** client |
| `GOOGLE_CLIENT_SECRET` | Client secret for that same OAuth client |
| `GOOGLE_REFRESH_TOKEN` | OAuth refresh token authorized with the `https://www.googleapis.com/auth/gmail.send` scope |
| `EMAIL_FROM` | Gmail account that authorized the OAuth access |
| `EMAIL_TO` | Email address that should receive daily reports |

Never commit OAuth credentials or tokens to the repository, and do not share them in issues or logs.

### Important: OAuth app in Testing mode

The Google OAuth app is currently in **Testing** mode. For an external app using Gmail scopes, refresh tokens generally expire after seven days while the app remains in Testing. When this happens, you must reauthorize the app and replace `GOOGLE_REFRESH_TOKEN` in GitHub Secrets. For unattended long-term operation, configure the required app homepage and privacy policy, then review Google's production/publishing requirements.

## How it works

1. Installs the Python Playwright package and Chromium in the temporary GitHub-hosted runner.
2. Opens the product page in headless Chromium and waits briefly for client-rendered content.
3. Looks for a price in JSON-LD structured data and common metadata.
4. Uses the Google OAuth refresh token to obtain an access token and sends the report through the Gmail API.
5. If fetching or parsing fails, attempts to email an error alert and marks the workflow run as failed. The runner is discarded when the job ends, so the browser installation does not persist.

## Limitations

- Playwright may help with pages that require JavaScript, but it does not guarantee access if eMAG blocks traffic from GitHub-hosted runners. The script does not attempt to bypass access controls. If no price can be identified confidently, it reports an error instead of guessing.
- The reported price is the listing price at check time, not a guaranteed checkout price.
- This workflow makes one request per day. Review eMAG's terms and site rules before running automated requests.
- GitHub scheduled workflows can start late; check the Actions tab if emails stop arriving.
