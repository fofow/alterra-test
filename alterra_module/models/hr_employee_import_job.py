# hr_employee_import_job.py
# -*- coding: utf-8 -*-
import logging
from odoo import models

_logger = logging.getLogger(__name__)

class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _job_create_employees_from_rows(self, rows):
        """
        Import tanpa validasi.
        - Jika work_email sudah ada di DB: SKIP (jangan update).
        - Jika work_email duplikat dalam satu file/job: SKIP (hanya ambil yang pertama).
        - Jika work_email kosong: tetap create.
        Semua skip dicatat ke log supaya bisa dilihat di Queue Job.
        """
        self = self.sudo()

        created = 0
        skipped_existing = 0
        skipped_infile = 0

        skipped_existing_list = []
        skipped_infile_list = []

        seen_in_file = set()  # track email yang sudah dipakai di job ini

        for r in rows or []:
            name = (r.get("name") or "").strip()
            if not name:
                # nama kosong → lewat
                continue

            email = (r.get("work_email") or "").strip().lower()
            job_title = (r.get("job_title") or "").strip() or False
            work_phone = (r.get("work_phone") or "").strip() or False

            # Jika email ada & sudah muncul sebelumnya di file → skip
            if email and email in seen_in_file:
                skipped_infile += 1
                skipped_infile_list.append(email)
                continue

            # Jika email ada & sudah ada record di DB → skip (jangan update)
            if email:
                exists = self.search([("work_email", "=", email)], limit=1)
                if exists:
                    skipped_existing += 1
                    skipped_existing_list.append(email)
                    # jangan tambahkan ke seen_in_file supaya baris selanjutnya
                    # dengan email sama tetap ditandai "existing", bukan "infile"
                    continue

            # Lolos semua: create
            vals = {
                "name": name,
                "work_email": email or False,
                "job_title": job_title,
                "work_phone": work_phone,
            }
            self.create(vals)
            created += 1

            # tandai email ini sudah dipakai di file (kalau ada)
            if email:
                seen_in_file.add(email)

        # Ringkasan log (dipotong supaya log tidak kebanyakan)
        def _sample(lst, n=20):
            return ", ".join(sorted(set(lst))[:n])

        _logger.info(
            "HR Import Job DONE: created=%s, skipped_existing=%s, skipped_infile=%s",
            created, skipped_existing, skipped_infile
        )
        if skipped_existing_list:
            _logger.warning(
                "Skipped existing emails (DB) count=%s sample=[%s]",
                skipped_existing, _sample(skipped_existing_list)
            )
        if skipped_infile_list:
            _logger.warning(
                "Skipped duplicate emails in file count=%s sample=[%s]",
                skipped_infile, _sample(skipped_infile_list)
            )

        return {
            "created": created,
            "skipped_existing": skipped_existing,
            "skipped_infile": skipped_infile,
        }


    def _job_notify_import_done(self):
        """Send an email notification that the import has finished."""
        self = self.sudo()
        template = self.env.ref("naska_hr_employee_import_async.mail_tmpl_hr_import_done", raise_if_not_found=False)
        if not template:
            return True

        # Prefer current user; fallback to admin if needed
        user = self.env.user
        if not user or not user.email:
            user = self.env.ref("base.user_admin", raise_if_not_found=False)

        if user and user.email:
            template.send_mail(user.id, force_send=True, email_values={"email_to": user.email})
        return True