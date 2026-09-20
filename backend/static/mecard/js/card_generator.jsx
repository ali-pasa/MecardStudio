const { useState, useEffect, useRef, useCallback } = React;

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

function parseAspectRatio(ratioStr) {
  if (!ratioStr) return 1.6;
  const parts = ratioStr.split(':').map(Number);
  if (parts.length === 2 && parts[1] !== 0) return parts[0] / parts[1];
  return 1.6;
}

function VariantCard({ card, index, isSelected, onSelect, registerIframe, aspectRatio }) {
  // Render at a fixed native size matching the real card aspect ratio,
  // then CSS-scale the whole iframe down. Since the AI now outputs ONLY
  // the card element (no page chrome), scaling shows the FULL card with
  // no internal scrollbar needed.
  const nativeWidth = 480;
  const nativeHeight = Math.round(nativeWidth / aspectRatio);
  const displayWidth = 300;
  const scale = displayWidth / nativeWidth;
  const displayHeight = Math.round(nativeHeight * scale);

  return (
    <div style={{
      border: isSelected ? '2px solid var(--brand)' : '1px solid var(--line)',
      borderRadius: 12, overflow: 'hidden', background: 'var(--surface-soft)',
    }}>
      <div style={{ padding: '10px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--line)' }}>
        <strong style={{ fontSize: 12 }}>Variant {index + 1}</strong>
        {isSelected ? (
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--brand)' }}>SELECTED</span>
        ) : (
          <button
            onClick={() => onSelect(card.id)}
            style={{ fontSize: 11, fontWeight: 700, background: 'none', border: 0, color: 'var(--muted)', cursor: 'pointer', textDecoration: 'underline' }}
          >
            Select this one
          </button>
        )}
      </div>
      <div style={{
        width: displayWidth, height: displayHeight, margin: '14px auto',
        overflow: 'hidden', borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,.12)',
      }}>
        <iframe
          ref={(el) => registerIframe(card.id, el)}
          title={`variant-${index}`}
          srcDoc={card.preview_html}
          style={{
            width: nativeWidth,
            height: nativeHeight,
            border: 0,
            background: '#fff',
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
          scrolling="no"
        />
      </div>
    </div>
  );
}

function CardGeneratorApp({ companyId, initialCategories }) {
  const [isOpen, setIsOpen] = useState(false);

  const [categories] = useState(initialCategories);
  const [categorySlug, setCategorySlug] = useState(
    initialCategories.length ? initialCategories[0].slug : ''
  );
  const [variantCount, setVariantCount] = useState(3);
  const [userPrompt, setUserPrompt] = useState('');
  const [referenceImage, setReferenceImage] = useState(null);
  const [referenceImagePreviewUrl, setReferenceImagePreviewUrl] = useState(null);
  const [variants, setVariants] = useState([]);
  const [generatedAspectRatio, setGeneratedAspectRatio] = useState(1.6);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(null);

  const liveNamesRef = useRef({ company_name: '', tagline: '' });
  const iframeRefs = useRef({});
  const fileInputRef = useRef(null);

  const registerIframe = useCallback((id, el) => {
    iframeRefs.current[id] = el;
  }, []);

  // Expose a global open function so the plain Django/JS "Create Card"
  // link (rendered outside React, in change_form.html) can trigger this
  // modal without needing its own toggle logic.
  useEffect(() => {
    window.mecardOpenCardGenerator = () => setIsOpen(true);
    return () => { delete window.mecardOpenCardGenerator; };
  }, []);

  // Live text sync into open preview iframes when the Django form's
  // company_name / tagline fields change, while the modal is open.
  useEffect(() => {
    if (!isOpen) return;
    const nameInput = document.getElementById('id_company_name');
    const taglineInput = document.getElementById('id_tagline');

    liveNamesRef.current.company_name = nameInput ? nameInput.value : '';
    liveNamesRef.current.tagline = taglineInput ? taglineInput.value : '';

    function syncTextInPreviews(oldValue, newValue) {
      if (!oldValue || oldValue === newValue) return;
      Object.values(iframeRefs.current).forEach((iframe) => {
        if (!iframe || !iframe.contentDocument) return;
        const walker = document.createTreeWalker(iframe.contentDocument.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (node.nodeValue.includes(oldValue)) {
            node.nodeValue = node.nodeValue.split(oldValue).join(newValue);
          }
        }
      });
    }

    function onNameInput(e) {
      syncTextInPreviews(liveNamesRef.current.company_name, e.target.value);
      liveNamesRef.current.company_name = e.target.value;
    }
    function onTaglineInput(e) {
      syncTextInPreviews(liveNamesRef.current.tagline, e.target.value);
      liveNamesRef.current.tagline = e.target.value;
    }

    if (nameInput) nameInput.addEventListener('input', onNameInput);
    if (taglineInput) taglineInput.addEventListener('input', onTaglineInput);

    return () => {
      if (nameInput) nameInput.removeEventListener('input', onNameInput);
      if (taglineInput) taglineInput.removeEventListener('input', onTaglineInput);
    };
  }, [isOpen, variants]);

  const handleImageSelect = (e) => {
    const file = e.target.files[0] || null;
    setReferenceImage(file);
    if (referenceImagePreviewUrl) URL.revokeObjectURL(referenceImagePreviewUrl);
    setReferenceImagePreviewUrl(file ? URL.createObjectURL(file) : null);
  };

  const clearImage = () => {
    setReferenceImage(null);
    if (referenceImagePreviewUrl) URL.revokeObjectURL(referenceImagePreviewUrl);
    setReferenceImagePreviewUrl(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const generate = useCallback(async () => {
    if (!categorySlug) return;
    setLoading(true);
    setError('');
    setVariants([]);

    const selectedCategory = categories.find((c) => c.slug === categorySlug);
    const ratio = parseAspectRatio(selectedCategory && selectedCategory.default_aspect_ratio);

    try {
      let response;

      if (referenceImage) {
        const formData = new FormData();
        formData.append('company_id', companyId);
        formData.append('category_slug', categorySlug);
        formData.append('name', 'ID Card');
        formData.append('variant_count', variantCount);
        if (userPrompt) formData.append('user_prompt', userPrompt);
        formData.append('reference_image', referenceImage);

        response = await fetch('/api/cards/generate/', {
          method: 'POST',
          headers: { 'X-CSRFToken': getCookie('csrftoken') },
          credentials: 'same-origin',
          body: formData,
        });
      } else {
        response = await fetch('/api/cards/generate/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
          },
          credentials: 'same-origin',
          body: JSON.stringify({
            company_id: companyId,
            category_slug: categorySlug,
            name: 'ID Card',
            variant_count: variantCount,
            user_prompt: userPrompt || undefined,
          }),
        });
      }

      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Generation failed.');

      setVariants(data.variants);
      setGeneratedAspectRatio(ratio);
      if (data.variants.length) setSelectedId(data.variants[0].id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [companyId, categorySlug, variantCount, userPrompt, referenceImage, categories]);

  const selectVariant = async (id) => {
    try {
      await fetch(`/api/cards/${id}/select/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCookie('csrftoken') },
        credentials: 'same-origin',
      });
      setSelectedId(id);
    } catch (err) {
      setError('Could not select this variant.');
    }
  };

  if (!isOpen) return null;

  return (
    <div
      onClick={() => setIsOpen(false)}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,.55)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: '5vh 24px', overflowY: 'auto',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(1150px, 100%)',
          background: 'var(--surface)', borderRadius: 16, boxShadow: 'var(--shadow)',
          padding: 28,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ margin: 0 }}>Create Card</h2>
          <button
            onClick={() => setIsOpen(false)}
            style={{ border: 0, background: 'none', fontSize: 24, lineHeight: 1, cursor: 'pointer', color: 'var(--muted)' }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 14 }}>
          <div style={{ flex: '1 1 220px' }}>
            <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>
              Card category
            </label>
            <select
              value={categorySlug}
              onChange={(e) => setCategorySlug(e.target.value)}
              style={{ width: '100%', minHeight: 42, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-soft)', color: 'var(--ink)', padding: '0 10px' }}
            >
              {categories.map((c) => (
                <option key={c.slug} value={c.slug}>{c.name}</option>
              ))}
            </select>
          </div>

          <div style={{ flex: '0 0 140px' }}>
            <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>
              Variants
            </label>
            <select
              value={variantCount}
              onChange={(e) => setVariantCount(Number(e.target.value))}
              style={{ width: '100%', minHeight: 42, borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-soft)', color: 'var(--ink)', padding: '0 10px' }}
            >
              {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>

          <div style={{ flex: '2 1 260px' }}>
            <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>
              Design instructions (optional)
            </label>
            <input
              type="text"
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
              placeholder="e.g. minimal, dark theme, rounded corners"
              style={{ width: '100%', minHeight: 42, boxSizing: 'border-box', borderRadius: 8, border: '1px solid var(--line)', background: 'var(--surface-soft)', color: 'var(--ink)', padding: '0 12px' }}
            />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ flex: '1 1 260px' }}>
            <label style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 700, color: 'var(--ink)' }}>
              Reference image (optional)
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleImageSelect}
                style={{ fontSize: 12, color: 'var(--muted)' }}
              />
              {referenceImage && (
                <button
                  type="button"
                  onClick={clearImage}
                  style={{ fontSize: 11, fontWeight: 700, background: 'none', border: 0, color: 'var(--muted)', cursor: 'pointer', textDecoration: 'underline' }}
                >
                  Remove
                </button>
              )}
            </div>
            <p style={{ margin: '6px 0 0', fontSize: 11, color: 'var(--muted)' }}>
              Upload an example card/badge design — the AI will use it as style inspiration while still applying this company's brand colors.
            </p>
          </div>

          {referenceImagePreviewUrl && (
            <img
              src={referenceImagePreviewUrl}
              alt="Reference preview"
              style={{ width: 80, height: 80, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--line)' }}
            />
          )}

          <button
            onClick={generate}
            disabled={loading || !categorySlug}
            className="primary-action"
            style={{ opacity: loading ? 0.6 : 1, marginLeft: 'auto' }}
          >
            {loading ? 'Generating…' : 'Generate'}
          </button>
        </div>

        {error && (
          <div style={{ marginBottom: 18, border: '1px solid #e6a6a6', borderRadius: 8, padding: '10px 12px', color: '#9a3030', background: '#fff1f1', fontSize: 12 }}>
            {error}
          </div>
        )}

        {variants.length > 0 && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${Math.min(variants.length, 3)}, minmax(0, 1fr))`,
            gap: 16,
            borderTop: '1px solid var(--line)',
            paddingTop: 20,
          }}>
            {variants.map((card, i) => (
              <VariantCard
                key={card.id}
                card={card}
                index={i}
                isSelected={card.id === selectedId}
                onSelect={selectVariant}
                registerIframe={registerIframe}
                aspectRatio={generatedAspectRatio}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const rootEl = document.getElementById('card-generator-root');
if (rootEl) {
  const companyId = rootEl.getAttribute('data-company-id');
  const categoriesDataEl = document.getElementById('card-categories-data');
  const initialCategories = categoriesDataEl ? JSON.parse(categoriesDataEl.textContent) : [];
  ReactDOM.createRoot(rootEl).render(
    <CardGeneratorApp companyId={companyId} initialCategories={initialCategories} />
  );
}