# naska_hr_employee_import_async

Odoo 18 module to import HR Employees asynchronously using OCA queue_job.
- Upload CSV/XLSX (columns: Name, Work Email, Job Title, Work Phone)
- Jobs are chunked (default 500 rows) and run in parallel on channel `hr_import`
- Optional email notification when finished

## Install
1. Ensure `queue_job` and `mail` are installed.
2. Copy this folder into your addons path.
3. Update app list and install **Async Employee Import (Queue Job)**.

## Config
In `odoo.conf`:
```
server_wide_modules = web,base,queue_job
; channels are defined in XML, but you can still set baseline concurrency for root:
; [queue_job]
; channels = root:2
```

Monitor jobs in Settings → Technical → Queue Jobs.