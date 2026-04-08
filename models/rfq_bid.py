from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Multiple vendors on one RFQ
    vendor_ids = fields.Many2many(
        'res.partner',
        'purchase_order_vendor_rel',
        'order_id',
        'partner_id',
        string='Assigned Vendors',
        domain=[('is_company', '=', True)],  # Only companies can be vendors
    )

    bid_ids = fields.One2many(
        'rfq.bid',
        'rfq_id',
        string='Bids',  # List of bids related to this RFQ
    )

    bid_count = fields.Integer(
        compute='_compute_bid_count',
        string='Bid Count',  # Total number of bids
    )

    winning_bid_id = fields.Many2one(
        'rfq.bid',
        string='Winning Bid',  # The selected winning bid
        readonly=True,
        copy=False,
    )

    purchase_request_id = fields.Many2one(
        'purchase.request',
        string='Purchase Request',  # Link to the purchase request
        readonly=True,
        copy=False,
    )

    @api.depends('bid_ids')
    def _compute_bid_count(self):
        # Compute the number of bids for each RFQ
        for order in self:
            order.bid_count = len(order.bid_ids)

    @api.onchange('vendor_ids')
    def _onchange_vendor_ids(self):
        # Automatically set the first vendor as the main partner
        if self.vendor_ids:
            self.partner_id = self.vendor_ids[0]
        else:
            self.partner_id = False

    @api.model_create_multi
    def create(self, vals_list):
        # Ensure the first vendor is set as the main partner during creation
        for vals in vals_list:
            if vals.get('vendor_ids') and not vals.get('partner_id'):
                for cmd in vals['vendor_ids']:
                    if cmd[0] == 6 and cmd[2]:  # Many2many commands
                        vals['partner_id'] = cmd[2][0]
                        break
                    elif cmd[0] == 4:  # Single record command
                        vals['partner_id'] = cmd[1]
                        break
        return super().create(vals_list)

    def write(self, vals):
        # Ensure the first vendor is set as the main partner during updates
        if vals.get('vendor_ids') and not vals.get('partner_id'):
            for cmd in vals['vendor_ids']:
                if cmd[0] == 6 and cmd[2]:  # Many2many commands
                    vals['partner_id'] = cmd[2][0]
                    break
                elif cmd[0] == 4:  # Single record command
                    vals['partner_id'] = cmd[1]
                    break
        return super().write(vals)

    def action_view_bids(self):
        # Open a view to see all bids related to this RFQ
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
        # Send the RFQ to vendors or use the default method if no vendors are assigned
        self.ensure_one()
        if not self.vendor_ids:
            return super().action_rfq_send()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send RFQ to Vendors'),
            'res_model': 'rfq.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rfq_id': self.id},
        }

    def action_open_select_winner(self):
        """Unified method: Check for bid amounts AND submitted status."""
        self.ensure_one()

        if not self.bid_ids:
            raise UserError(_('No bids have been received for this RFQ yet.'))

        # 1. Validation: All bids must have an amount greater than 0
        missing_amounts = self.bid_ids.filtered(lambda b: b.bid_amount <= 0.0)
        if missing_amounts:
            vendor_names = ", ".join(missing_amounts.mapped('vendor_id.name'))
            raise UserError(_(
                "Incomplete Data: You must enter a bid amount for all vendors before "
                "selecting a winner. Missing amounts for: %s"
            ) % vendor_names)

        # 2. Validation: All bids must be in 'Submitted' state
        not_submitted = self.bid_ids.filtered(lambda b: b.state != 'submitted')
        if not_submitted:
            vendor_names = ", ".join(not_submitted.mapped('vendor_id.name'))
            raise UserError(_(
                "Action Required: All bids must be in 'Submitted' state. "
                "The following vendors are still in Draft or other states: %s"
            ) % vendor_names)

        # Open a wizard to select the winning bid
        return {
            'type': 'ir.actions.act_window',
            'name': _('Select Winning Bid'),
            'res_model': 'rfq.select.winner.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_rfq_id': self.id},
        }