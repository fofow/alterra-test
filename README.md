# Alterra Test Skills
## Import Asyncronus Employee & Invoice API
### Install
1. Ensure `queue_job` and `mail` and `auth_api_key` and `alterra_modules` are installed.
2. Copy this folder into your addons path.
3. Update app list and install **Alterra Modules**.

### Config
In `odoo.conf`:
```
; [options]
; longpolling_port = False
; web.base.url = [[host]]
; server_wide_modules = web, base, auth_api_key,queue_job
; gevent_port = 8072
; websocket = True
; proxy_mode = True
; x_sendfile = False
; workers = 2
; max_cron_threads = 1

```

## Usage

### Import Employee

```
go to Menu → Employee → Asyncronus Import Employee
fill the form and click import.
test file is include in repo

Monitor jobs in `Menu → Job Queue → Jobs`.

```

### API Invoice

link of api documentation: https://swagger.bassam-dev.icu/
