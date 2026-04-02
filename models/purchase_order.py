from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Many2many field to assign multiple vendors to a purchase order
    vendor_ids = fields.Many2many(
        'res.partner',
        'purchase_order_vendor_rel',
        'order_id',
        'partner_id',
        string='Assigned Vendors',
        domain=[('is_company', '=', True)],  # Only companies can be assigned
    )
    # One2many field to track bids related to the RFQ
    bid_ids = fields.One2many(
        'rfq.bid',
        'rfq_id',
        string='Bids',
    )
    # Computed field to count the number of bids
    bid_count = fields.Integer(
        compute='_compute_bid_count',
        string='Bid Count',
    )
    # Field to store the winning bid (if any)
    winning_bid_id = fields.Many2one(
        'rfq.bid',
        string='Winning Bid',
        readonly=True,
        copy=False,
    )
    # Field to link the purchase order to a purchase request
    purchase_request_id = fields.Many2one(
        'purchase.request',
        string='Purchase Request',
        readonly=True,
        copy=False,
    )

    @api.depends('bid_ids')
    def _compute_bid_count(self):
        # Compute the number of bids for each purchase order
        for order in self:
            order.bid_count = len(order.bid_ids)

    @api.onchange('vendor_ids')
    def _onchange_vendor_ids(self):
        # Ensure partner_id is in sync with vendor_ids to avoid validation errors
        if self.vendor_ids:
            self.partner_id = self.vendor_ids[0]
        else:
            self.partner_id = False

    @api.model_create_multi
    def create(self, vals_list):
        # Ensure partner_id is set based on vendor_ids during creation
        for vals in vals_list:
            if vals.get('vendor_ids') and not vals.get('partner_id'):
                for cmd in vals['vendor_ids']:
                    if cmd[0] == 6 and cmd[2]:  # Command to set multiple vendors
                        vals['partner_id'] = cmd[2][0]
                        break
                    elif cmd[0] == 4:  # Command to add a single vendor
                        vals['partner_id'] = cmd[1]
                        break
        return super().create(vals_list)

    def write(self, vals):
        # Ensure partner_id is updated based on vendor_ids during updates
        if vals.get('vendor_ids') and not vals.get('partner_id'):
            for cmd in vals['vendor_ids']:
                if cmd[0] == 6 and cmd[2]:  # Command to set multiple vendors
                    vals['partner_id'] = cmd[2][0]
                    break
                elif cmd[0] == 4:  # Command to add a single vendor
                    vals['partner_id'] = cmd[1]
                    break
        return super().write(vals)

    def action_view_bids(self):
        # Open a view to display all bids related to this RFQ
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bids'),
            'res_model': 'rfq.bid',
            'view_mode': 'list,form',
            'domain': [('rfq_id', '=', self.id)],
            'context': {'default_rfq_id': self.id},
        }

    def action_rfq_send(self):
        # Send RFQ emails to all assigned vendors
        self.ensure_one()
        if not self.vendor_ids:
            return super(PurchaseOrder, self).action_rfq_send()

        # Update supplier_rank for vendors without purchase history
        self.vendor_ids.filtered(
            lambda v: v.supplier_rank == 0
        ).write({'supplier_rank': 1})

        original_partner = self.partner_id  # Save the original partner_id

        try:
            for vendor in self.vendor_ids:
                # Temporarily set partner_id to the current vendor and send RFQ
                super(PurchaseOrder, self).write({'partner_id': vendor.id})
                super(PurchaseOrder, self).action_rfq_send()
        finally:
            # Restore the original partner_id after sending RFQs
            super(PurchaseOrder, self).write({'partner_id': original_partner.id})

    def action_open_select_winner(self):
        # Open a wizard to select the winning bid for this RFQ
        self.ensure_one()
        if not self.bid_ids:
            raise UserError(_('No bids have been received for this RFQ yet.'))
        submitted = self.bid_ids.filtered(lambda b: b.state == 'submitted')
        if not submitted:
            raise UserError(_(
                'No bids are in Submitted state. '
                'Bids must be submitted before selecting a winner.'
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Select Winning Bid'),
            'res_model': 'rfq.select.winner.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rfq_id': self.id},
        }
