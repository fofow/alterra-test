{
    "name": "Alterra Test Skill ",
    "summary": "1. Async Employee Import (Queue Job)\n Import HR Employees asynchronously via OCA queue_job with chunking and optional email notice",
    "version": "18.0.1.0.0",
    "author": "Faris",
    "license": "LGPL-3",
    "depends": ["hr", "queue_job", "mail", "auth_api_key"],
    "data": [
        "data/mail_template.xml",
        "security/ir.model.access.csv",
        "views/queue_job_config.xml",
        "views/hr_employee_import_views.xml",
    ],
    "installable": True,
    "application": False
}
