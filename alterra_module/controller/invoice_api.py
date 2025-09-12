import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# Ensure controller is registered at module load time
class InvoiceController(http.Controller):

    @http.route('/api/ping', type='http', auth='api_key', methods=['GET'], csrf=False, sitemap=False)
    def ping(self):
        return Response(
            json.dumps({"status": "ok", "message": "API is running"}),
            status=200,
            content_type='application/json'
        )

    @http.route('/api/test', type='http', auth='api_key', methods=['GET'], csrf=False, sitemap=False)
    def test_endpoint(self):
        return Response(
            json.dumps({
                "status": "authenticated",
                "user":  request.env.user.name,
                "user_id": request.env.user.id,
                "api_key_id": getattr(request, 'auth_api_key_id', None)
            }),
            status=200,
            content_type='application/json'
        )

    # Get List Invoices
    @http.route('/api/invoices', type='http', auth='api_key', methods=['GET'], csrf=False)
    def list_invoices(self, **params):
        domain = []
        if params.get('partner_id'):
            domain.append(('partner_id', '=', int(params['partner_id'])))
        if params.get('state'):
            domain.append(('state', '=', params['state']))
        moves = request.env['account.move'].search(domain, limit=int(params.get('limit', 50)))
        data = []
        for m in moves:
            payments = [{
                'payment_id': p.id,
                'amount': p.amount,
                'journal_id': p.journal_id.id,
                'date': p.date,
            } for p in m._get_reconciled_payments()] if params.get('with_payments') else []
            data.append({
                'id': m.id,
                'name': m.name,
                'partner_id': m.partner_id.id,
                'partner_name': m.partner_id.name,
                'amount_total': m.amount_total,
                'state': m.state,
                'payments': payments,
            })
        return Response(
            json.dumps({
                'count': len(data), 
                'data': data
            }),
            status=200,
            content_type='application/json'
        )


    # Create a new Invoice
    @http.route('/api/invoices', type='http', auth='api_key', methods=['POST'], csrf=False)
    def create_invoices(self, **payload):
        try:
            data = json.loads(request.httprequest.data.decode())
        except Exception:
            return Response(json.dumps({'error': 'Invalid JSON'}), status=400, content_type='application/json')

        items = data.get('items') or []
        if not isinstance(items, list) or not items:
            return Response(json.dumps({'error': 'items must be a non-empty list'}), status=400,
                            content_type='application/json')

        created_ids = []
        errors = []

        for it in items:
            try:
                with request.env.cr.savepoint():
                    move_vals = self._prepare_move_vals(it)
                    move = request.env['account.move'].create(move_vals)
                    created_ids.append(move.id)
            except Exception as e:
                _logger.exception('Create invoice failed: %s', e)
                errors.append({'item': it, 'error': str(e)})

        status_code = 201 if created_ids else 400
        result = {'count': len(created_ids), 'data': created_ids}
        if errors:
            result['errors'] = errors

        return Response(json.dumps(result), status=status_code, content_type='application/json')



    # Update Invoices
    @http.route('/api/invoices/<int:move_id>', type='http', auth='api_key', methods=['PUT'], csrf=False)
    def update_invoice(self, move_id, **payload):
        move = request.env['account.move'].browse(move_id)
        if not move.exists():
            return Response(json.dumps({'error': 'Invoice not found'}), status=404, content_type='application/json')

        if move.state == 'posted':
            return Response(json.dumps({'error': 'Cannot update posted invoice'}), status=400,
                            content_type='application/json')

        try:
            data = json.loads(request.httprequest.data.decode())
        except Exception:
            return Response(json.dumps({'error': 'Invalid JSON'}), status=400, content_type='application/json')

        update_vals = data.get('items', [{}])[0]
        _logger.info('Update invoice %s with values %s', move_id, update_vals)

        try:
            with request.env.cr.savepoint():
                if 'lines' in update_vals:
                    lines_vals = update_vals.pop('lines') or []
                    # Clear existing lines
                    move.invoice_line_ids = [(5, 0, 0)]
                    for line in lines_vals:
                        line_vals = {
                            'product_id': line.get('product_id'),
                            'quantity': line.get('quantity', 1.0),
                            'price_unit': line.get('price_unit', 0.0),
                            'name': line.get('name', '/'),
                        }
                        if line.get('tax_ids'):
                            line_vals['tax_ids'] = [(6, 0, line['tax_ids'])]
                        move.invoice_line_ids = [(0, 0, line_vals)]
                if update_vals:
                    move.write(update_vals)
        except Exception as e:
            _logger.exception('Update invoice failed: %s', e)
            return Response(json.dumps({'error': str(e)}), status=400, content_type='application/json')

        return Response(json.dumps({'updated_id': move.id}), status=200, content_type='application/json')


    # Register Payments
    @http.route('/api/invoices/register-payments', type='http', auth='api_key', methods=['POST'], csrf=False)
    def register_payments(self, **payload):
        try:
            data = json.loads(request.httprequest.data.decode())
        except Exception:
            return Response(json.dumps({'error': 'Invalid JSON'}), status=400, content_type='application/json')

        items = data.get('items') or []
        results = []

        for it in items:
            move_id = it.get('invoice_id')
            amount = it.get('amount')
            journal_id = it.get('journal_id')
            move = request.env['account.move'].browse(int(move_id))

            # if not move.exists() or move.state != 'posted':
            #     results.append({'invoice_id': move_id, 'status': 'skip', 'reason': 'not found or not posted'})
            #     continue
            if not move.exists():
                results.append({'invoice_id': move_id, 'status': 'skip', 'reason': 'not found'})
                continue
            elif move.state == 'draft':
                results.append({'invoice_id': move_id, 'status': 'skip', 'reason': 'Invoice State still in draft'})
                continue
            elif move.state != 'posted':
                results.append({'invoice_id': move_id, 'status': 'skip', 'reason': 'Invoice State is already posted'})
                continue
            try:
                with request.env.cr.savepoint():
                    wiz = request.env['account.payment.register'].with_context(
                        active_model='account.move', active_ids=[move.id]
                    ).create({
                        'amount': amount,
                        'journal_id': journal_id,
                    })
                    wiz.action_create_payments()
                results.append({'invoice_id': move.id, 'status': 'ok'})
            except Exception as e:
                _logger.exception('Register payment failed: %s', e)
                results.append({'invoice_id': move.id, 'status': 'error', 'reason': str(e)})

        return Response(json.dumps({'results': results}), status=200, content_type='application/json')


    def _prepare_move_vals(self, item):
        partner_id = item.get('partner_id')
        lines = item.get('lines') or []
        if not partner_id or not lines:
            raise ValueError(_('partner_id and lines are required'))

        aml = []
        for l in lines:
            line_vals = {
                'name': l.get('name') or '/',
                'quantity': l.get('quantity', 1.0),
                'price_unit': l['price_unit'],
            }
            # kalau ada product_id, Odoo otomatis pilih akun
            if l.get('product_id'):
                line_vals['product_id'] = l['product_id']
            # optional: tax_ids kalau memang dikirim
            if l.get('tax_ids'):
                line_vals['tax_ids'] = [(6, 0, l['tax_ids'])]

            aml.append((0, 0, line_vals))

        return {
            'move_type': item.get('move_type', 'out_invoice'),  # customer invoice default
            'partner_id': partner_id,
            'invoice_date': item.get('invoice_date'),
            'invoice_line_ids': aml,
        }