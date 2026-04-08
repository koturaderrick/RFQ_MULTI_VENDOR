from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseRequest(models.Model):
    _name = 'purchase.request'
    _description = 'Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc'

    name = fields.Char(
        string='Request Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted to Procurement'),
        ('approved', 'Approved'),
        ('rfq_created', 'RFQ Created'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True)

    requested_by = fields.Many2one(
        'res.users',
        string='Requested By',
        default=lambda self: self.env.user,
        required=True,
    )

    date_request = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        required=True,
    )

    date_required = fields.Date(string='Required By', required=True)
    description = fields.Text(string='Justification', required=True)

    vendor_ids = fields.Many2many(
        'res.partner',
        'purchase_request_vendor_rel',
        'request_id',
        'partner_id',
        string='Vendors to Invite',
        domain=[('supplier_rank', '>', 0)],
        help='Vendors to send RFQs to once this request is approved.',
    )

    line_ids = fields.One2many(
        'purchase.request.line',
        'request_id',
        string='Requested Items',
    )

    rfq_ids = fields.One2many(
        'purchase.order',
        'purchase_request_id',
        string='RFQs',
    )

    rfq_count = fields.Integer(compute='_compute_rfq_count', string='RFQs')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('purchase.request') or _('New')
                )
        return super().create(vals_list)

    @api.depends('rfq_ids')
    def _compute_rfq_count(self):
        for rec in self:
            rec.rfq_count = len(rec.rfq_ids)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one item before submitting.'))
            rec.state = 'submitted'

    def action_approve(self):
        for rec in self:
            rec.state = 'approved'

    def action_reject(self):
        for rec in self:
            rec.state = 'rejected'

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_create_rfq(self):
        self.ensure_one()
        if not self.vendor_ids:
            raise UserError(_('Please add at least one vendor.'))

        # 1. Create the RFQ
        po = self.env['purchase.order'].create({
            'purchase_request_id': self.id,
            'origin': self.name,
            'order_line': [(0, 0, {
                'product_id': l.product_id.id,
                'name': l.description or l.product_id.name,
                'product_qty': l.qty,
                'product_uom_id': l.uom_id.id,
                'price_unit': l.estimated_price,
            }) for l in self.line_ids],
            'vendor_ids': [(6, 0, self.vendor_ids.ids)],
        })

        # 2. Automatically create Bid records
        for vendor in self.vendor_ids:
            self.env['rfq.bid'].create({
                'rfq_id': po.id,
                'vendor_id': vendor.id,
                'state': 'submitted',
                'bid_amount': 0.0,
            })

        self.state = 'rfq_created'
        return self.action_view_rfqs()

    def action_view_rfqs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('RFQs'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('purchase_request_id', '=', self.id)],
        }


class PurchaseRequestLine(models.Model):
    _name = 'purchase.request.line'
    _description = 'Purchase Request Line'

    request_id = fields.Many2one('purchase.request', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    description = fields.Char(string='Description')
    qty = fields.Float(string='Quantity', default=1.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', required=True)
    estimated_price = fields.Float(string='Estimated Unit Price')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.name
            tmpl = self.product_id.product_tmpl_id
            self.uom_id = getattr(tmpl, 'uom_po_id', False) or self.product_id.uom_id
            self.estimated_price = self.product_id.standard_price