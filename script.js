/*
 * Common JavaScript for interactive elements across the finance portfolio.
 *
 * This script provides modal functionality that is reused on multiple pages.
 * It allows you to attach explanations and optional images to any item by
 * storing the content in localStorage. Each explanation is keyed by a
 * simple string (e.g. "cash", "variance-analysis"). When a visitor
 * clicks on a line item, the modal opens, loading any previously saved
 * text and image. After editing, you can save or expand the content to a
 * dedicated page.
 */

// State variable to track which item is currently being edited in the modal
let currentItemKey = null;

/**
 * Initialise event listeners on all anchors with the data-item attribute.
 * This function should be called once after the DOM has loaded. It
 * attaches a click handler that prevents default navigation and opens
 * the modal instead.
 */
function initModalTriggers() {
  document.querySelectorAll('a[data-item]').forEach(function(el) {
    el.addEventListener('click', function(event) {
      event.preventDefault();
      const key = el.getAttribute('data-item');
      openModal(key);
    });
  });
}

/**
 * Open the modal for a given item key. Loads any saved content and
 * prepares the modal for editing.
 * @param {string} key - Identifier for the item being edited
 */
function openModal(key) {
  currentItemKey = key;
  const modal = document.getElementById('modal');
  if (!modal) return;
  // Load any saved data from localStorage
  const stored = localStorage.getItem('explanation_' + key);
  let text = '';
  let imageData = '';
  if (stored) {
    try {
      const obj = JSON.parse(stored);
      text = obj.text || '';
      imageData = obj.image || '';
    } catch (e) {
      console.error('Error parsing saved content', e);
    }
  }
  // Populate textarea
  const textarea = modal.querySelector('textarea');
  if (textarea) textarea.value = text;
  // Show image preview if present
  const imgPreview = modal.querySelector('.image-preview');
  if (imgPreview) {
    if (imageData) {
      imgPreview.src = imageData;
      imgPreview.style.display = 'block';
    } else {
      imgPreview.style.display = 'none';
    }
  }
  // Reset file input
  const fileInput = modal.querySelector('input[type="file"]');
  if (fileInput) fileInput.value = '';
  // Show modal
  modal.style.display = 'flex';
}

/**
 * Close the modal without saving changes.
 */
function closeModal() {
  const modal = document.getElementById('modal');
  if (modal) modal.style.display = 'none';
  currentItemKey = null;
}

/**
 * Save the content from the modal to localStorage. Converts any
 * uploaded image to a data URL for storage. After saving, the
 * modal is closed.
 */
function saveModal() {
  const modal = document.getElementById('modal');
  if (!modal || !currentItemKey) return;
  const textarea = modal.querySelector('textarea');
  const fileInput = modal.querySelector('input[type="file"]');
  const imgPreview = modal.querySelector('.image-preview');
  let text = textarea ? textarea.value : '';
  // Helper to finalise storage once image (if any) is processed
  function storeContent(imageData) {
    const obj = { text: text, image: imageData || '' };
    localStorage.setItem('explanation_' + currentItemKey, JSON.stringify(obj));
    closeModal();
  }
  // If a file is selected, read it as data URL
  if (fileInput && fileInput.files && fileInput.files[0]) {
    const reader = new FileReader();
    reader.onload = function(e) {
      const dataURL = e.target.result;
      // Update image preview
      if (imgPreview) {
        imgPreview.src = dataURL;
        imgPreview.style.display = 'block';
      }
      storeContent(dataURL);
    };
    reader.readAsDataURL(fileInput.files[0]);
  } else {
    // No new image selected; if preview already shows an image, reuse it
    const existing = imgPreview && imgPreview.style.display !== 'none' ? imgPreview.src : '';
    storeContent(existing);
  }
}

/**
 * Navigate to a dedicated explanation page for the current item.
 * The page reads the item key from the query string and loads the
 * corresponding explanation.
 */
function expandModal() {
  if (!currentItemKey) return;
  window.open('explanation.html?item=' + encodeURIComponent(currentItemKey), '_blank');
}

/**
 * Read a query parameter from the URL. Used by explanation.html to
 * determine which item to load.
 * @param {string} name - Parameter name
 * @returns {string|null} - Parameter value or null if absent
 */
function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

/**
 * Load content for explanation.html. This function should be called on
 * page load to populate the title, textarea and image with any saved
 * data. If no data is found, the fields are left blank.
 */
function initExplanationPage() {
  const item = getQueryParam('item');
  if (!item) return;
  const heading = document.getElementById('item-heading');
  if (heading) {
    // Format item key into human-readable text
    heading.textContent = item.replace(/-/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
  }
  const textarea = document.getElementById('item-text');
  const imgPreview = document.getElementById('item-image');
  const stored = localStorage.getItem('explanation_' + item);
  if (stored) {
    try {
      const obj = JSON.parse(stored);
      if (textarea) textarea.value = obj.text || '';
      if (imgPreview) {
        if (obj.image) {
          imgPreview.src = obj.image;
          imgPreview.style.display = 'block';
        } else {
          imgPreview.style.display = 'none';
        }
      }
    } catch (e) {
      console.error('Error parsing explanation data', e);
    }
  }
  // Save handler for explanation page
  const saveBtn = document.getElementById('save-explanation');
  if (saveBtn) {
    saveBtn.addEventListener('click', function() {
      const fileInput = document.getElementById('item-file');
      function storeContent(imageData) {
        const obj = { text: textarea.value, image: imageData || '' };
        localStorage.setItem('explanation_' + item, JSON.stringify(obj));
        alert('Saved successfully');
      }
      if (fileInput && fileInput.files && fileInput.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
          const dataURL = e.target.result;
          if (imgPreview) {
            imgPreview.src = dataURL;
            imgPreview.style.display = 'block';
          }
          storeContent(dataURL);
        };
        reader.readAsDataURL(fileInput.files[0]);
      } else {
        const existing = imgPreview && imgPreview.style.display !== 'none' ? imgPreview.src : '';
        storeContent(existing);
      }
    });
  }
}

// Initialise triggers when the script loads. If DOMContentLoaded has
// already fired, run immediately; otherwise attach a listener. This
// ensures that modal triggers are always set up, even when the script
// is included at the end of the HTML document.
function initPageScripts() {
  // If a modal exists on this page, set up triggers
  if (document.getElementById('modal')) {
    initModalTriggers();
    // Close modal when clicking outside the content
    const modal = document.getElementById('modal');
    modal.addEventListener('click', function(event) {
      if (event.target === modal) {
        closeModal();
      }
    });
  }
  // If explanation page elements exist, initialise them
  if (document.getElementById('item-heading')) {
    initExplanationPage();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPageScripts);
} else {
  initPageScripts();
}