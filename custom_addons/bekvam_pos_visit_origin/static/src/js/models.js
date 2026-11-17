odoo.define('bekvam_pos_visit_origin.models', function (require) {
    'use strict';
    const {Order, PosGlobalState} = require('point_of_sale.models');
    const Registries = require('point_of_sale.Registries');
    const policy = require('bekvam_pos_visit_origin.policy');
    const OriginOrder = Base => class extends Base {
        constructor() {
            super(...arguments);
            this.bekvam_visit_type = this.bekvam_visit_type || false;
            this.bekvam_discovery_channel = this.bekvam_visit_type === 'first_visit'
                ? this.bekvam_discovery_channel || false : false;
        }
        init_from_JSON(json) {
            super.init_from_JSON(...arguments);
            this.bekvam_visit_type = json.bekvam_visit_type || false;
            this.bekvam_discovery_channel = this.bekvam_visit_type === 'first_visit'
                ? json.bekvam_discovery_channel || false : false;
            this.bekvam_sync_uncertain = json.bekvam_sync_uncertain || false;
            this.bekvam_sync_snapshot = json.bekvam_sync_snapshot || false;
        }
        export_as_JSON() {
            return {...super.export_as_JSON(...arguments),
                bekvam_visit_type: this.bekvam_visit_type || false,
                bekvam_discovery_channel: this.bekvam_visit_type === 'first_visit'
                    ? this.bekvam_discovery_channel || false : false,
                bekvam_sync_uncertain: this.bekvam_sync_uncertain || false,
                bekvam_sync_snapshot: this.bekvam_sync_snapshot || false};
        }
        set_bekvam_origin(visit, channel) {
            this.assert_editable();
            this.bekvam_visit_type = visit || false;
            this.bekvam_discovery_channel = visit === 'first_visit' ? channel || false : false;
            this.save_to_db();
        }
        save_to_db() {
            if ((this.bekvam_sync_uncertain || this.bekvam_sync_snapshot) && !this.temporary && !this.locked && !this.finalized) {
                return this.pos.db.save_unpaid_order(this);
            }
            return super.save_to_db(...arguments);
        }
        set_partner(partner) {
            const previous = this.get_partner();
            const changed = (previous && previous.id) !== (partner && partner.id);
            if (changed && (this.bekvam_sync_uncertain || this.bekvam_sync_snapshot || this._bekvam_accepted)) {
                throw new Error('Verifique la sincronizacion antes de cambiar el cliente.');
            }
            const result = super.set_partner(...arguments);
            if (changed && !this.finalized) this.set_bekvam_origin(false, false);
            return result;
        }
        assert_editable() {
            if ((this.bekvam_sync_uncertain || this.bekvam_sync_snapshot) && !this._bekvam_recovering) {
                throw new Error('La confirmacion esta pendiente. Reintente la verificacion antes de editar.');
            }
            return super.assert_editable(...arguments);
        }
    };
    const OriginPos = Base => class extends Base {
        push_single_order(order, options) {
            // Reuse an accepted result inside the normal finalization chain, not a second sale.
            if (order._bekvam_accepted) return Promise.resolve(order._bekvam_accepted);
            return super.push_single_order(...arguments);
        }
        async bekvam_rpc(method, data) {
            return this.env.services.rpc({model: 'pos.order', method, args: [data],
                kwargs: {context: this.env.session.user_context}});
        }
        async bekvam_accept_before_receipt(order) {
            if (order._bekvam_accepted) return order._bekvam_accepted;
            let data = order.bekvam_sync_snapshot || order.export_as_JSON();
            // Always recover first: a response can have been lost after a committed sale.
            let result = await this.bekvam_rpc('bekvam_recover_origin_order', data);
            order.bekvam_sync_uncertain = false;
            if (order.bekvam_sync_snapshot) {
                // Core 16 does not restore to_invoice, and the fiscal addon does not restore
                // full_number in init_from_JSON. Restore them from our immutable retry packet.
                order.to_invoice = Boolean(data.to_invoice);
                order.to_ship = Boolean(data.to_ship);
                for (const key of Object.keys(data).filter(key => key.startsWith('l10n_cr_edi_'))) {
                    order[key] = data[key];
                }
            }
            if (!result.length) {
                if (order.bekvam_sync_snapshot) {
                    // A successful recovery lookup established that this sale does not exist.
                    // Unlock correction and allocate a fresh sequence if another sale used it.
                    order.bekvam_sync_snapshot = false;
                    order.l10n_cr_edi_full_number = false;
                    order.l10n_cr_edi_number = false;
                }
                data = order.export_as_JSON();
                await this.bekvam_rpc('bekvam_validate_origin', data);
                if (order.set_l10n_cr_edi_information) await order.set_l10n_cr_edi_information();
                order.initialize_validation_date();
                const snapshot = order.export_as_JSON();
                delete snapshot.bekvam_sync_snapshot;
                delete snapshot.bekvam_sync_uncertain;
                order.bekvam_sync_snapshot = JSON.parse(JSON.stringify(snapshot));
                this.db.save_unpaid_order(order);
                try {
                    result = await this.push_single_order(order);
                } catch (error) {
                    // Do not leave a separate paid queue entry that could sync behind the editable draft.
                    this.db.remove_order(order.uid);
                    order.bekvam_sync_uncertain = true;
                    this.db.save_unpaid_order(order);
                    throw error;
                }
            }
            if (!Array.isArray(result) || result.length !== 1 || !result[0].id) {
                order.bekvam_sync_uncertain = true;
                this.db.save_unpaid_order(order);
                throw new Error('No se recibio una confirmacion unica del servidor. Verifique antes de reintentar.');
            }
            order._bekvam_accepted = result;
            order.bekvam_sync_uncertain = false;
            this.db.remove_order(order.uid);
            return result;
        }
    };
    Registries.Model.extend(Order, OriginOrder);
    Registries.Model.extend(PosGlobalState, OriginPos);
    return {OriginOrder, OriginPos};
});
