odoo.define('bekvam_pos_visit_origin.policy', function (require) {
    'use strict';
    const visits = ['first_visit', 'previous_visit'];
    const channels = ['facebook', 'instagram', 'tiktok', 'google', 'referral', 'mall'];
    function active(config, now = Date.now()) {
        if (!config.bekvam_origin_scope || !config.bekvam_origin_required_from) return false;
        const start = Date.parse(config.bekvam_origin_required_from.replace(' ', 'T') + 'Z');
        return Number.isFinite(start) && now >= start;
    }
    function needsCapture(order) {
        return active(order.pos.config) && order.get_orderlines().some(line => line.get_quantity() > 0);
    }
    function strictSync(order) {
        // Do not use the workstation clock to decide whether server acknowledgement is required.
        return Boolean(order.pos.config.bekvam_origin_scope && order.pos.config.bekvam_origin_required_from
            && order.get_orderlines().length > 0);
    }
    function error(visit, channel) {
        if (!visits.includes(visit)) return 'Indique si es su primera visita a una tienda Bekvam.';
        if (visit === 'first_visit' && !channels.includes(channel)) return 'Seleccione como conocio Bekvam.';
        if (visit === 'previous_visit' && channel) return 'Borre el canal al seleccionar visita previa.';
        return '';
    }
    function partnerError(order) {
        if (!needsCapture(order)) return '';
        const partner = order.get_partner();
        const fallback = order.pos.config.bekvam_default_partner_id;
        const fallbackId = Array.isArray(fallback) ? fallback[0] : fallback;
        return !partner || partner.id === fallbackId
            ? 'Seleccione un cliente identificado antes de continuar; Consumidor Final no es valido.' : '';
    }
    async function prompt(component, props) {
        const pos = component.env.pos;
        pos._bekvam_origin_popup_depth = (pos._bekvam_origin_popup_depth || 0) + 1;
        try { return await component.showPopup('BekvamOriginPopup', props); }
        finally { pos._bekvam_origin_popup_depth = Math.max(0, (pos._bekvam_origin_popup_depth || 1) - 1); }
    }
    async function ensure(component, order) {
        if (!needsCapture(order)) return true;
        const missingPartner = partnerError(order);
        if (missingPartner) {
            await component.showPopup('ErrorPopup', {title: 'Cliente requerido', body: missingPartner});
            return false;
        }
        if (!error(order.bekvam_visit_type, order.bekvam_discovery_channel)) return true;
        const {confirmed, payload} = await prompt(component, {
            visit: order.bekvam_visit_type || '', channel: order.bekvam_discovery_channel || '',
        });
        if (!confirmed || component.env.pos.get_order() !== order) return false;
        if (error(payload.visit, payload.channel)) return false;
        order.set_bekvam_origin(payload.visit, payload.channel);
        return true;
    }
    return {active, needsCapture, strictSync, error, partnerError, ensure, prompt, visits, channels};
});
