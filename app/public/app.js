/* global $ */
const money = v => Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function loadHistory() {
  $.getJSON('/api/history').done(rows => {
    if (!rows.length) {
      $('#historyBody').html('<tr><td colspan="6" class="text-secondary">No calculations yet.</td></tr>');
      return;
    }
    $('#historyBody').html(rows.map(r => `<tr>
      <td>${esc(new Date(r.createdAt).toLocaleString())}</td>
      <td class="text-end">${money(r.principal)}</td>
      <td class="text-end">${esc(r.rate)}</td>
      <td class="text-end">${esc(r.months)}</td>
      <td class="text-end">${money(r.emi)}</td>
      <td><span class="pod-tag">${esc(r.servedBy)}</span></td></tr>`).join(''));
  });
}

function validField($el, ok) { $el.toggleClass('is-invalid', !ok); return ok; }

$('#emiForm').on('submit', function (e) {
  e.preventDefault();                      // no postback - AJAX only
  $('#formError').addClass('d-none');
  const P = parseFloat($('#P').val()), rate = parseFloat($('#rate').val()), n = Number($('#n').val());
  const ok = [
    validField($('#P'), isFinite(P) && P > 0),
    validField($('#rate'), isFinite(rate) && rate > 0 && rate <= 100),
    validField($('#n'), Number.isInteger(n) && n > 0 && n <= 600),
  ].every(Boolean);
  if (!ok) return;

  $('#calcBtn').prop('disabled', true).text('Calculating...');
  $.ajax({ url: '/api/emi', method: 'POST', contentType: 'application/json', data: JSON.stringify({ P, rate, n }) })
    .done(r => {
      $('#resultEmpty').addClass('d-none');
      $('#resultBody').removeClass('d-none');
      $('#rEmi').text(money(r.emi));
      $('#rTotal').text(money(r.totalPayment));
      $('#rInterest').text(money(r.totalInterest));
      $('#rPod').text(r.servedBy);
      $('#rIp').text(r.podIP);
      loadHistory();
    })
    .fail(xhr => {
      const b = xhr.responseJSON || {};
      $('#formError').removeClass('d-none').text((b.errors || [b.error || 'The server could not be reached. Try again.']).join(' '));
    })
    .always(() => $('#calcBtn').prop('disabled', false).text('Calculate EMI'));
});

loadHistory();
