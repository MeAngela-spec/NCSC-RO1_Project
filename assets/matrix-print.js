'use strict';

// Wait for the official letterhead before opening the native print dialog.
async function printMatrixPage() {
  const button = document.getElementById('printMatrixAgain');
  button.disabled = true;
  try {
    await Promise.all([...document.images].map(image => image.decode()));
    if (document.fonts) await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    window.print();
    button.textContent = 'Print again';
  } catch (error) {
    button.textContent = 'Retry print';
    document.querySelector('.print-toolbar p').textContent = 'The letterhead could not load. Reopen Print matrix from the register or retry.';
  } finally { button.disabled = false; }
}
document.getElementById('printMatrixAgain').addEventListener('click', printMatrixPage);
printMatrixPage();
