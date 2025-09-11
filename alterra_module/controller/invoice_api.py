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
        # return self._json({'invoices': data})
        return Response(
            json.dumps({
                'count': len(data), 
                'data': data
            }),
            status=200,
            content_type='application/json'
        )




    """Create a new Invoice"""
    @http.route('/api/invoices', type='http', auth='api_key', methods=['POST'], csrf=False)
    def create_invoices(self, **payload):
        # user = self._require_api_key()
        # if not user:
        #     return self._error('Unauthorized', 401)
        _logger.info('paaaaaaaaaaaaaaaaayyy: %s', payload)

        # items = payload.get('items') or []


        try:
            data = json.loads(request.httprequest.data.decode())
        except Exception:
            return Response(
                json.dumps({'error': 'Invalid JSON'}),
                status=400,
                content_type='application/json'
            )

        items = data.get('items') or []

        _logger.info('items: %s', items)
        if not isinstance(items, list) or not items:
            return Response(
                json.dumps({'error': 'items must be a non-empty list'}),
                status=400,
                content_type='application/json'
            )

        created_ids = []
        for it in items:
            try:
                move_vals = self._prepare_move_vals(it)
                move = request.env['account.move'].create(move_vals)
                created_ids.append(move.id)
            except Exception as e:
                _logger.exception('Create invoice failed: %s', e)
                return Response(
                    json.dumps({'error': str(e)}),
                    status=400,
                    content_type='application/json'
                )
        return Response(
            json.dumps({
                'count': len(created_ids), 
                'data': created_ids
            }),
            status=201,
            content_type='application/json'
        )




# Update Invoices
    @http.route('/api/invoices/<int:move_id>', type='http', auth='api_key', methods=['PUT'], csrf=False)
    def update_invoice(self, move_id, **payload):
        user = self._require_api_key()
        if not user:
            return self._error('Unauthorized', 401)
        move = request.env['account.move'].with_user(user).browse(move_id)
        if not move.exists():
            return self._error('Invoice not found', 404)
        if move.state == 'posted':
            return self._error('Cannot update posted invoice', 400)
        try:
            vals = payload.get('values') or {}
            move.write(vals)
        except Exception as e:
            _logger.exception('Update invoice failed: %s', e)
            return self._error(str(e))
        return self._json({'updated_id': move.id})

    # Register Payments
    @http.route('/api/invoices/register-payments', type='http', auth='api_key', methods=['POST'], csrf=False)
    def register_payments(self, **payload):
        user = self._require_api_key()
        if not user:
            return self._error('Unauthorized', 401)
        items = payload.get('items') or []
        results = []
        for it in items:
            move_id = it.get('invoice_id')
            amount = it.get('amount')
            journal_id = it.get('journal_id')
            move = request.env['account.move'].with_user(user).browse(int(move_id))
            if not move.exists() or move.state != 'posted':
                results.append({'invoice_id': move_id, 'status': 'skip', 'reason': 'not found or not posted'})
                continue
                # Use the official wizard so reconciliation rules are respected
            wiz = request.env['account.payment.register'].with_user(user).with_context(
                active_model='account.move', active_ids=[move.id]
            ).create({
                'amount': amount,
                'journal_id': journal_id,
            })
            try:
                act = wiz.action_create_payments()
                results.append({'invoice_id': move.id, 'status': 'ok'})
            except Exception as e:
                _logger.exception('Register payment failed: %s', e)
                results.append({'invoice_id': move.id, 'status': 'error', 'reason': str(e)})
        return self._json({'results': results})



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
    # @http.route('/api/members', type='http', auth='api_key', methods=['POST'], csrf=False)
    # def create_member(self, **post):
    #     """Create a new member"""
    #     try:
    #         # Parse JSON data from request body
    #         data = json.loads(request.httprequest.data.decode('utf-8')) if request.httprequest.data else {}
            
    #         # Required fields
    #         name = data.get('name')
    #         phone = data.get('phone')
            
    #         if not name or not phone:
    #             return Response(
    #                 json.dumps({'error': 'Name and phone are required fields'}),
    #                 status=400,
    #                 content_type='application/json'
    #             )
            
    #         # Check if partner already exists with this phone
    #         existing_partner = request.env['res.partner'].sudo().search([('phone', '=', phone)], limit=1)
    #         if existing_partner:
    #             return Response(
    #                 json.dumps({
    #                     'error': 'A member with this phone number already exists', 
    #                     'id': existing_partner.id
    #                 }),
    #                 status=400,
    #                 content_type='application/json'
    #             )
            
    #         # Create the partner
    #         vals = {
    #             'name': name,
    #             'phone': phone,
    #             'email': data.get('email'),
    #             'street': data.get('street'),
    #             'city': data.get('city'),
    #             'zip': data.get('zip'),
    #             'member_code': data.get('member_code'),
    #             'country_id': data.get('country_id'),
    #             'is_company': False,
    #             'customer_rank': 1,
    #             'free_member': True,
    #         }
            
    #         partner = request.env['res.partner'].sudo().create(vals)
            
    #         # Associate with membership
    #         if partner:
    #             # Get the free membership product if exists
    #             free_membership = request.env['product.product'].sudo().search([
    #                 ('membership', '=', True),
    #                 ('membership_date_from', '=', False),
    #                 ('membership_date_to', '=', False),
    #             ], limit=1)
                
    #             if free_membership:
    #                 # Create membership line
    #                 membership_line_vals = {
    #                     'partner': partner.id,
    #                     'membership_id': free_membership.id,
    #                     'state': 'paid',  # Set as paid for free membership
    #                 }
    #                 request.env['membership.membership_line'].sudo().create(membership_line_vals)
            
    #         return Response(
    #             json.dumps({
    #                 'success': True,
    #                 'id': partner.id,
    #                 'name': partner.name,
    #                 'phone': partner.phone,
    #                 'member_code': partner.member_code or '',
    #                 'membership_state': partner.membership_state
    #             }),
    #             status=201,
    #             content_type='application/json'
    #         )
            
    #     except Exception as e:
    #         _logger.error("Error creating member: %s", str(e))
    #         return Response(
    #             json.dumps({'error': str(e)}),
    #             status=500,
    #             content_type='application/json'
    #         )


    # @http.route('/api/members', type='http', auth='api_key', methods=['GET'], csrf=False)
    # def list_members(self, **kwargs):
    #     """List all members"""
    #     try:
    #         limit = int(kwargs.get('limit', 100))
    #         offset = int(kwargs.get('offset', 0))
            
    #         # Get members - filter for partners with membership
    #         members = request.env['res.partner'].sudo().search([
    #             ('membership_state', 'not in', ['none', 'canceled']),
    #             ('is_company', '=', False)
    #         ], limit=limit, offset=offset)
            
    #         result = []
    #         for member in members:
    #             result.append({
    #                 'id': member.id,
    #                 'name': member.name,
    #                 'phone': member.phone,
    #                 'email': member.email,
    #                 'member_code': member.member_code or '',
    #                 # 'membership_state': member.membership_state,
    #                 # 'membership_start': member.membership_start and member.membership_start.strftime('%Y-%m-%d') or False,
    #                 # 'membership_stop': member.membership_stop and member.membership_stop.strftime('%Y-%m-%d') or False,
    #             })
            
    #         return Response(
    #             json.dumps({
    #                 'count': len(result), 
    #                 'data': result
    #             }),
    #             status=200,
    #             content_type='application/json'
    #         )
            
    #     except Exception as e:
    #         _logger.error("Error listing members: %s", str(e))
    #         return Response(
    #             json.dumps({'error': str(e)}),
    #             status=500,
    #             content_type='application/json'
    #         )
    
    # @http.route('/api/member/<string:identifier>', type='http', auth='api_key', methods=['GET'], csrf=False)
    # def get_member_by_phone(self, identifier, **kwargs):
    #     """Get member by phone number or member code"""
    #     try:
    #         # Search by both phone and member_code
    #         member = request.env['res.partner'].sudo().search([
    #             '|',
    #             ('phone', '=', identifier),
    #             ('member_code', '=', identifier),
    #             ('is_company', '=', False)
    #         ], limit=1)
            
    #         if not member:
    #             return Response(
    #                 json.dumps({'error': 'Member not found with this phone number or member code'}),
    #                 status=404,
    #                 content_type='application/json'
    #             )
            
    #         # Get membership details
    #         membership_lines = request.env['membership.membership_line'].sudo().search([
    #             ('partner', '=', member.id)
    #         ])
            
    #         membership_history = []
    #         for line in membership_lines:
    #             membership_history.append({
    #                 'id': line.id,
    #                 'member_code': line.partner.member_code or '',
    #                 'membership_id': line.membership_id.id,
    #                 'membership_name': line.membership_id.name,
    #                 'state': line.state,
    #                 'date_from': line.date_from and line.date_from.strftime('%Y-%m-%d') or False,
    #                 'date_to': line.date_to and line.date_to.strftime('%Y-%m-%d') or False,
    #             })
            
    #         return Response(
    #             json.dumps({
    #                 'id': member.id,
    #                 'name': member.name,
    #                 'phone': member.phone,
    #                 'email': member.email,
    #                 'street': member.street,
    #                 'city': member.city,
    #                 'zip': member.zip,
    #                 'member_code': member.member_code,
    #                 'country': member.country_id.name if member.country_id else None,
    #                 'membership_state': member.membership_state,
    #                 'membership_start': member.membership_start and member.membership_start.strftime('%Y-%m-%d') or False,
    #                 'membership_stop': member.membership_stop and member.membership_stop.strftime('%Y-%m-%d') or False,
    #                 'membership_history': membership_history
    #             }),
    #             status=200,
    #             content_type='application/json'
    #         )
            
    #     except Exception as e:
    #         _logger.error("Error getting member by phone: %s", str(e))
    #         return Response(
    #             json.dumps({'error': str(e)}),
    #             status=500,
    #             content_type='application/json'
    #         )
    
    # @http.route('/api/member/<string:identifier>/transactions', type='http', auth='api_key', methods=['GET'], csrf=False)
    # def get_member_transactions(self, identifier, **kwargs):
    #     """Get all transactions for a member by phone number or member code"""
    #     try:
    #         # Get date range parameters
    #         date_from = kwargs.get('date_from')  # Format: YYYY-MM-DD
    #         date_to = kwargs.get('date_to')      # Format: YYYY-MM-DD

    #         # Search by both phone and member_code
    #         member = request.env['res.partner'].sudo().search([
    #             '|',
    #             ('phone', '=', identifier),
    #             ('member_code', '=', identifier),
    #             ('is_company', '=', False)
    #         ], limit=1)
            
    #         if not member:
    #             return Response(
    #                 json.dumps({'error': 'Member not found with this phone number or member code'}),
    #                 status=404,
    #                 content_type='application/json'
    #             )
            
    #         # Build search domain for POS orders
    #         domain = [('partner_id', '=', member.id)]

    #         # Add date filtering if provided
    #         if date_from:
    #             try:
    #                 # Convert to datetime and add to domain
    #                 from datetime import datetime
    #                 date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
    #                 domain.append(('create_date', '>=', date_from_dt))
    #             except ValueError:
    #                 return Response(
    #                     json.dumps({'error': 'Invalid date_from format. Use YYYY-MM-DD'}),
    #                     status=400,
    #                     content_type='application/json'
    #                 )

    #         if date_to:
    #             try:
    #                 # Convert to datetime (end of day) and add to domain
    #                 from datetime import datetime, timedelta
    #                 date_to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    #                 domain.append(('create_date', '<=', date_to_dt))
    #             except ValueError:
    #                 return Response(
    #                     json.dumps({'error': 'Invalid date_to format. Use YYYY-MM-DD'}),
    #                     status=400,
    #                     content_type='application/json'
    #                 )

    #         # Get POS orders for this member with date filtering
    #         pos_orders = request.env['pos.order'].sudo().search(domain)
            
    #         transactions = []
    #         for order in pos_orders:
    #             # Get primary payment method
    #             primary_payment = order.payment_ids[0] if order.payment_ids else None
                
    #             # Calculate amounts
    #             subtotal_amount = sum(line.price_subtotal for line in order.lines if line.price_subtotal >= 0)
    #             tax_amount = order.amount_tax
    #             service_charge = 0
    #             shipping_price = 0
    #             # Discount appears as separate product with negative amount
    #             discount_amount = abs(sum(line.price_subtotal for line in order.lines if line.price_subtotal < 0))
                
    #             # Split customer name
    #             name_parts = member.name.split(' ', 1) if member.name else ['', '']
    #             first_name = name_parts[0]
    #             last_name = name_parts[1] if len(name_parts) > 1 else ''

    #             transaction = {
    #                 "no_order": order.name or order.pos_reference,
    #                 "order_date": order.date_order.strftime('%d-%m-%Y') if order.date_order else '',
    #                 "outlet": order.session_id.config_id.name if order.session_id else 1,
    #                 "transaction_payment_method": primary_payment.payment_method_id.name if primary_payment else '',
    #                 "transaction_payment_code": primary_payment.payment_method_id.code if primary_payment and hasattr(primary_payment.payment_method_id, 'code') else '',
    #                 "transaction_discount_amount": discount_amount,
    #                 "transaction_subtotal_amount": subtotal_amount,
    #                 "transaction_bill_amount": order.amount_total,
    #                 "transaction_payment_amount": sum(payment.amount for payment in order.payment_ids),
    #                 "transaction_tax": tax_amount,
    #                 "transaction_service_charge": service_charge,
    #                 "shipping_price": shipping_price,
    #                 "customer_details": {
    #                     "member_code": member.member_code or '',
    #                     "first_name": first_name,
    #                     "last_name": last_name,
    #                     "email": member.email or '',
    #                     "phone": member.phone or ''
    #                 },
    #                 "is_pickup": '-',
    #                 "pickup_store": order.session_id.config_id.name if order.session_id else 1,
    #                 "shipping_address": {
    #                     "id": member.id,
    #                     "first_name": first_name,
    #                     "last_name": last_name,
    #                     "phone": member.phone.replace('+62 ', '') if member.phone else '',
    #                     "id_coverage": "-",
    #                     "address": member.street or ''
    #                 },
    #                 "note": order.note if hasattr(order, 'note') else ''
    #             }
                
    #             transactions.append(transaction)

    #         return Response(
    #             json.dumps({
    #                 'member_id': member.id,
    #                 'member_code': member.member_code or '',
    #                 'member_name': member.name,
    #                 'member_phone': member.phone,
    #                 'transaction_count': len(transactions),
    #                 'transactions': transactions,
    #                 'total_transactions': sum(order.amount_total for order in pos_orders)
    #             }),
    #             status=200,
    #             content_type='application/json'
    #         )
            
    #     except Exception as e:
    #         _logger.error("Error getting member transactions: %s", str(e))
    #         return Response(
    #             json.dumps({'error': str(e)}),
    #             status=500,
    #             content_type='application/json'
    #         )

    # @http.route('/api/transactions/summary', type='http', auth='api_key', methods=['GET'], csrf=False)
    # def get_transactions_summary(self, **kwargs):
    #     """Get aggregated transaction summary for all members by date range and optional outlet filter"""
    #     try:
    #         # Get parameters
    #         date_from = kwargs.get('date_from')  # Format: YYYY-MM-DD
    #         date_to = kwargs.get('date_to')      # Format: YYYY-MM-DD
    #         outlet = kwargs.get('outlet')        # Outlet name filter

    #         # Build search domain for POS orders
    #         domain = []

    #         # Add outlet filtering if provided
    #         if outlet:
    #             # Find POS config with matching name
    #             pos_config = request.env['pos.config'].sudo().search([('name', '=', outlet)], limit=1)
    #             if pos_config:
    #                 # Filter by session config
    #                 sessions = request.env['pos.session'].sudo().search([('config_id', '=', pos_config.id)])
    #                 if sessions:
    #                     domain.append(('session_id', 'in', sessions.ids))
    #                 else:
    #                     # If no sessions found for this config, return empty result
    #                     domain.append(('id', '=', False))
    #             else:
    #                 # If outlet not found, return empty result
    #                 domain.append(('id', '=', False))

    #         # Add date filtering if provided
    #         if date_from:
    #             try:
    #                 # Convert to datetime and add to domain
    #                 from datetime import datetime
    #                 date_from_dt = datetime.strptime(date_from, '%Y-%m-%d')
    #                 domain.append(('create_date', '>=', date_from_dt))
    #             except ValueError:
    #                 return Response(
    #                     json.dumps({'error': 'Invalid date_from format. Use YYYY-MM-DD'}),
    #                     status=400,
    #                     content_type='application/json'
    #                 )

    #         if date_to:
    #             try:
    #                 # Convert to datetime (end of day) and add to domain
    #                 from datetime import datetime, timedelta
    #                 date_to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
    #                 domain.append(('create_date', '<=', date_to_dt))
    #             except ValueError:
    #                 return Response(
    #                     json.dumps({'error': 'Invalid date_to format. Use YYYY-MM-DD'}),
    #                     status=400,
    #                     content_type='application/json'
    #                 )

    #         # Get all POS orders with date filtering
    #         pos_orders = request.env['pos.order'].sudo().search(domain)

    #         transactions = []

    #         for order in pos_orders:
    #             # Only process transactions from members with valid member_code
    #             if not order.partner_id or not order.partner_id.member_code:
    #                 continue

    #             # Get primary payment method
    #             primary_payment = order.payment_ids[0] if order.payment_ids else None

    #             # Calculate amounts
    #             subtotal_amount = sum(line.price_subtotal for line in order.lines if line.price_subtotal >= 0)
    #             tax_amount = order.amount_tax
    #             service_charge = 0
    #             shipping_price = 0
    #             # Discount appears as separate product with negative amount
    #             discount_amount = abs(sum(line.price_subtotal for line in order.lines if line.price_subtotal < 0))

    #             # Split customer name
    #             name_parts = order.partner_id.name.split(' ', 1) if order.partner_id.name else ['', '']
    #             first_name = name_parts[0]
    #             last_name = name_parts[1] if len(name_parts) > 1 else ''

    #             # Build order list with product details
    #             order_list = []
    #             for line in order.lines:
    #                 product_item = {
    #                     "product_code": line.product_id.default_code or '',
    #                     "name": line.product_id.name or '',
    #                     "description": line.product_id.description_sale or line.product_id.description or '',
    #                     "category_name": line.product_id.categ_id.name if line.product_id.categ_id else '',
    #                     "price": line.price_unit,
    #                     "quantity": int(line.qty)
    #                 }
    #                 order_list.append(product_item)

    #             transaction = {
    #                 "no_order": order.name or order.pos_reference,
    #                 "order_date": order.date_order.strftime('%d-%m-%Y') if order.date_order else '',
    #                 "outlet": order.session_id.config_id.name if order.session_id else 1,
    #                 "transaction_payment_method": primary_payment.payment_method_id.name if primary_payment else '',
    #                 "transaction_payment_code": primary_payment.payment_method_id.code if primary_payment and hasattr(primary_payment.payment_method_id, 'code') else '',
    #                 "transaction_discount_amount": discount_amount,
    #                 "transaction_subtotal_amount": subtotal_amount,
    #                 "transaction_bill_amount": order.amount_total,
    #                 "transaction_payment_amount": sum(payment.amount for payment in order.payment_ids),
    #                 "transaction_tax": tax_amount,
    #                 "transaction_service_charge": service_charge,
    #                 "shipping_price": shipping_price,
    #                 "customer_details": {
    #                     "member_code": order.partner_id.member_code or '',
    #                     "first_name": first_name,
    #                     "last_name": last_name,
    #                     "email": order.partner_id.email or '',
    #                     "phone": order.partner_id.phone or ''
    #                 },
    #                 "is_pickup": '-',
    #                 "pickup_store": order.session_id.config_id.name if order.session_id else 1,
    #                 "shipping_address": {
    #                     "id": order.partner_id.id,
    #                     "first_name": first_name,
    #                     "last_name": last_name,
    #                     "phone": order.partner_id.phone.replace('+62 ', '') if order.partner_id.phone else '',
    #                     "id_coverage": "-",
    #                     "address": order.partner_id.street or ''
    #                 },
    #                 "note": order.note if hasattr(order, 'note') else '',
    #                 "order_list": order_list
    #             }

    #             transactions.append(transaction)

    #         # Prepare response data
    #         response_data = {
    #             'date_range': {
    #                 'date_from': date_from,
    #                 'date_to': date_to
    #             },
    #             'outlet_filter': outlet,
    #             'transaction_count': len(transactions),
    #             'transactions': transactions,
    #             'total_transaction_amount': sum(t['transaction_bill_amount'] for t in transactions)
    #         }

    #         return Response(
    #             json.dumps(response_data),
    #             status=200,
    #             content_type='application/json'
    #         )

    #     except Exception as e:
    #         _logger.error("Error getting transactions summary: %s", str(e))
    #         return Response(
    #             json.dumps({'error': str(e)}),
    #             status=500,
    #             content_type='application/json'
    #         )

    # @http.route('/api/members/<string:member_code>', type='http', auth='api_key', methods=['PUT'], csrf=False)
    # def update_member_by_code(self, member_code, **kwargs):
    #     """Update member by member code"""
    #     try:
    #         # Parse JSON data from request body
    #         data = json.loads(request.httprequest.data.decode('utf-8')) if request.httprequest.data else {}

    #         member = request.env['res.partner'].sudo().search([
    #             ('member_code', '=', member_code),
    #             ('is_company', '=', False)
    #         ], limit=1)

    #         if not member:
    #             return Response(
    #                 json.dumps({'error': 'Member not found with this member code'}),
    #                 status=404,
    #                 content_type='application/json'
    #             )

    #         # Update allowed fields
    #         update_vals = {}
    #         allowed_fields = ['name', 'phone', 'email', 'street', 'city', 'zip']

    #         for field in allowed_fields:
    #             if field in data:
    #                 update_vals[field] = data[field]

    #         if update_vals:
    #             member.write(update_vals)

    #         return Response(
    #             json.dumps({
    #                 'success': True,
    #                 'id': member.id,
    #                 'name': member.name,
    #                 'phone': member.phone,
    #                 'member_code': member.member_code,
    #             }),
    #             status=200,
    #             content_type='application/json'
    #         )

    #     except Exception as e:
    #         return Response(
    #             json.dumps({'error': str(e)}),
    #             status=500,
    #             content_type='application/json'
    #         )