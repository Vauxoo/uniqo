odoo.define('bekvam_pos_visit_origin.screens', function (require) {
    'use strict';
    const ProductScreen = require('point_of_sale.ProductScreen');
    const PaymentScreen = require('point_of_sale.PaymentScreen');
    const Chrome = require('point_of_sale.Chrome');
    const {OrderValidationPopup} = require('@pos_uniqo/js/Popups/OrderValidationPopup');
    const Registries = require('point_of_sale.Registries');
    const policy = require('bekvam_pos_visit_origin.policy');

    const OriginProducts = Base => class extends Base {
        async _onClickPay() {
            if (!await policy.ensure(this, this.env.pos.get_order())) return;
            return super._onClickPay(...arguments);
        }
    };
    const OriginPayment = Base => class extends Base {
        async addNewPaymentLine() {
            if (!await policy.ensure(this, this.currentOrder)) return false;
            return super.addNewPaymentLine(...arguments);
        }
        async _sendPaymentRequest() {
            if (!await policy.ensure(this, this.currentOrder)) return;
            if (!policy.strictSync(this.currentOrder)) return super._sendPaymentRequest(...arguments);
            try {
                await this.env.pos.bekvam_rpc('bekvam_validate_origin', this.currentOrder.export_as_JSON());
            } catch (error) {
                await this.showPopup('ErrorPopup', {title: 'No se inicio el cobro', body: error.message || 'Verifique conexion y datos.'});
                return;
            }
            return super._sendPaymentRequest(...arguments);
        }
        async validateOrder() {
            if (!await policy.ensure(this, this.currentOrder)) return;
            return super.validateOrder(...arguments);
        }
        async _isOrderValid() {
            if (!await policy.ensure(this, this.currentOrder)) return false;
            return super._isOrderValid(...arguments);
        }
        async _finalizeValidation() {
            const order = this.currentOrder;
            if (!policy.strictSync(order)) return super._finalizeValidation(...arguments);
            if (order._bekvam_finalizing) return;
            order._bekvam_finalizing = true;
            let blocked = false;
            try {
                if (!await policy.ensure(this, order)) return;
                // Sync before invoking the upstream finally block that always opens the receipt.
                // Cache the result so fiscal/credit hooks can run normally without sending twice.
                this.env.services.ui.block();
                blocked = true;
                await this.env.pos.bekvam_accept_before_receipt(order);
                this.env.services.ui.unblock();
                blocked = false;
                if (this.currentOrder !== order) throw new Error('Vuelva al pedido que se acaba de verificar.');
                order._bekvam_recovering = true;
                return await super._finalizeValidation(...arguments);
            } catch (error) {
                if (blocked) { this.env.services.ui.unblock(); blocked = false; }
                if (!order._bekvam_accepted) {
                    order.finalized = false;
                    this.env.pos.db.save_unpaid_order(order);
                    await this.showPopup('ErrorPopup', {title: 'Venta sin confirmar',
                        body: 'No vuelva a cobrar. Reintente la verificacion con conexion. ' +
                            (error.data && error.data.message || error.message || '')});
                    return;
                }
                // The sale was already accepted. A PDF/receipt error is not a new payment attempt.
                throw error;
            } finally {
                if (blocked) this.env.services.ui.unblock();
                order._bekvam_recovering = false;
                order._bekvam_finalizing = false;
            }
        }
        async editBekvamOrigin() {
            const order = this.currentOrder;
            if (!policy.needsCapture(order)) return;
            if (order.bekvam_sync_uncertain || order.bekvam_sync_snapshot || order._bekvam_accepted) {
                await this.showPopup('ErrorPopup', {title: 'Verificacion pendiente',
                    body: 'Reintente confirmar para consultar el resultado antes de cambiar la respuesta.'});
                return;
            }
            const {confirmed, payload} = await policy.prompt(this, {
                visit: order.bekvam_visit_type || '', channel: order.bekvam_discovery_channel || '',
            });
            if (confirmed && !policy.error(payload.visit, payload.channel)) order.set_bekvam_origin(payload.visit, payload.channel);
        }
        get bekvamOriginLabel() {
            const order = this.currentOrder;
            if (!policy.needsCapture(order)) return '';
            return order.bekvam_visit_type === 'first_visit' ? 'Primera visita' :
                order.bekvam_visit_type === 'previous_visit' ? 'Visita previa' : 'Respuesta pendiente';
        }
    };
    const OriginValidationPopup = Base => class extends Base {
        get bekvamOriginLabel() {
            if (!policy.needsCapture(this.order)) return '';
            return this.order.bekvam_visit_type === 'first_visit' ? 'Primera visita' : 'Visita previa';
        }
        async confirm() {
            if (!await policy.ensure(this, this.order)) return;
            const route = this.validateRouteSelectionForProducts();
            if (!route.isValid) { this.state.validationMessage = route.message; return; }
            // Narrow workaround for the reviewed vendor assignment that happens after validation.
            if (policy.strictSync(this.order) && this.state.routeId) {
                const routeId = parseInt(this.state.routeId, 10);
                if (!this.availableRoutes.some(candidate => candidate.id === routeId)) {
                    this.state.validationMessage = 'Seleccione una ruta disponible.';
                    return;
                }
                this.order.get_orderlines().filter(line => line.product.type === 'product')
                    .forEach(line => { line.route_id = routeId; });
                this.order.save_to_db();
            }
            return super.confirm(...arguments);
        }
    };
    const OriginChrome = Base => class extends Base {
        _actionAfterIdle() {
            if (this.env.pos._bekvam_origin_popup_depth) {
                // Keep restaurant idle behavior except while this mandatory question is open.
                if (this._setIdleTimer) this._setIdleTimer();
                return;
            }
            return super._actionAfterIdle(...arguments);
        }
    };
    Registries.Component.extend(ProductScreen, OriginProducts);
    Registries.Component.extend(PaymentScreen, OriginPayment);
    Registries.Component.extend(OrderValidationPopup, OriginValidationPopup);
    Registries.Component.extend(Chrome, OriginChrome);
    return {OriginProducts, OriginPayment, OriginValidationPopup, OriginChrome};
});
