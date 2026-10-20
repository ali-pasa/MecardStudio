const { useState, useEffect, useRef, useCallback } = React;

const generationMessages = [
  'Analyzing your reference design',
  'Creating different card compositions',
  'Applying your company brand colors',
  'Building polished card layouts',
  'Preparing your design previews',
];

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return parts.pop().split(';').shift();
  }
  return '';
}

async function readApiResponse(response, fallbackMessage) {
  const responseText = await response.text();

  let data;

  try {
    data = JSON.parse(responseText);
  } catch {
    if (response.redirected) {
      throw new Error(
        'Your session may have expired. Refresh the page, sign in again, and retry.'
      );
    }

    if (response.status === 403) {
      throw new Error(
        'The request was blocked. Refresh the page and try again.'
      );
    }

    if (response.status === 404) {
      throw new Error(
        'The card API endpoint was not found. Restart the backend and refresh this page.'
      );
    }

    const errorPage = new DOMParser().parseFromString(
      responseText,
      'text/html'
    );

    const serverMessage =
      errorPage.querySelector('.exception_value')?.textContent ||
      errorPage.querySelector('title')?.textContent;

    const detail = serverMessage
      ? ` Server detail: ${serverMessage
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 300)}`
      : '';

    throw new Error(
      `${fallbackMessage} The server returned an unexpected page (HTTP ${response.status}).${detail}`
    );
  }

  if (!response.ok) {
    throw new Error(
      data.error ||
        data.detail ||
        fallbackMessage
    );
  }

  return data;
}


/* ============================================================
   Variant Card
   ============================================================ */

function VariantCard({
  card,
  index,
  isSelected,
  onToggle,
  aspectRatio,
  disabled,
}) {
  /*
   * These are the native design canvas dimensions.
   *
   * Horizontal:
   * 856 x 540
   *
   * Vertical:
   * 540 x 856
   *
   * The AI generator should generate HTML using the same canvas.
   */

  const nativeWidth =
    aspectRatio >= 1
      ? 856
      : 540;

  const nativeHeight =
    aspectRatio >= 1
      ? 540
      : 856;

  const previewRef = useRef(null);
  const [previewWidth, setPreviewWidth] = useState(nativeWidth);

  useEffect(() => {
    const preview = previewRef.current;

    if (!preview) {
      return undefined;
    }

    const updateWidth = () => {
      const width = preview.clientWidth;

      if (width > 0) {
        setPreviewWidth(Math.min(nativeWidth, width));
      }
    };

    updateWidth();

    const resizeObserver = new ResizeObserver(() => {
      updateWidth();
    });

    resizeObserver.observe(preview);

    return () => {
      resizeObserver.disconnect();
    };
  }, [nativeWidth]);

  const scale = previewWidth / nativeWidth;

  return (
    <div
      style={{
        border: isSelected
          ? '2px solid var(--brand)'
          : '1px solid var(--line)',

        borderRadius: 14,
        overflow: 'hidden',

        background: isSelected
          ? 'rgba(31, 111, 139, .06)'
          : 'var(--surface)',

        boxShadow: isSelected
          ? '0 0 0 3px rgba(31, 111, 139, .13)'
          : '0 8px 22px rgba(20, 40, 55, .08)',

        transition:
          'border-color .18s ease, box-shadow .18s ease, background .18s ease',
      }}
    >
      {/* Variant header */}
      <div
        style={{
          minHeight: 58,
          boxSizing: 'border-box',
          padding: '10px 14px',

          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,

          borderBottom: '1px solid var(--line)',
        }}
      >
        <div>
          <strong
            style={{
              display: 'block',
              color: 'var(--ink)',
              fontSize: 13,
            }}
          >
            Design {index + 1}
          </strong>

          <span
            style={{
              color: 'var(--muted)',
              fontSize: 11,
            }}
          >
            Preview
          </span>
        </div>

        <label
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 7,

            flex: '0 0 auto',

            border: isSelected
              ? '1px solid var(--brand)'
              : '1px solid var(--line)',

            borderRadius: 999,
            padding: '7px 11px',

            color: isSelected
              ? 'var(--brand-deep)'
              : 'var(--muted)',

            background: isSelected
              ? 'var(--surface)'
              : 'transparent',

            fontSize: 11,
            fontWeight: 700,

            cursor: disabled
              ? 'not-allowed'
              : 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={isSelected}
            disabled={disabled}
            onChange={() => onToggle(card.id)}
            style={{
              width: 15,
              height: 15,
              margin: 0,
              accentColor: 'var(--brand)',
            }}
          />

          {isSelected ? 'Selected' : 'Select'}
        </label>
      </div>

      {/* Preview */}
      <div
        ref={previewRef}
        style={{
          position: 'relative',

          width: 'calc(100% - 28px)',
          maxWidth: nativeWidth,

          /*
           * The preview container keeps the correct card ratio.
           */
          aspectRatio: `${nativeWidth} / ${nativeHeight}`,

          margin: '14px auto',

          overflow: 'hidden',

          borderRadius: 9,

          background: '#f1f4f6',

          boxShadow:
            '0 8px 22px rgba(15, 35, 50, .13)',
        }}
      >
        <iframe
          title={`Design ${index + 1} preview`}
          srcDoc={card.preview_html}
          scrolling="no"
          style={{
            position: 'absolute',

            top: 0,
            left: 0,

            width: `${nativeWidth}px`,
            height: `${nativeHeight}px`,

            border: 0,

            background: '#fff',

            transform: `scale(${scale})`,
            transformOrigin: 'top left',

            pointerEvents: 'none',
          }}
        />
      </div>
    </div>
  );
}


/* ============================================================
   Card Generator
   ============================================================ */

function CardGeneratorApp({
  companyId,
  initialCategories,
}) {
  const [isOpen, setIsOpen] = useState(false);

  const [categories] = useState(
    Array.isArray(initialCategories)
      ? initialCategories
      : []
  );

  const [categorySlug, setCategorySlug] = useState(
    initialCategories.length
      ? initialCategories[0].slug
      : ''
  );

  const [orientation, setOrientation] =
    useState('horizontal');

  const [variantCount, setVariantCount] =
    useState(3);

  const [userPrompt, setUserPrompt] =
    useState('');

  const [referenceImage, setReferenceImage] =
    useState(null);

  const [
    referenceImagePreviewUrl,
    setReferenceImagePreviewUrl,
  ] = useState(null);

  const [variants, setVariants] =
    useState([]);

  const [generatedAspectRatio, setGeneratedAspectRatio] =
    useState(1.6);

  const [loading, setLoading] =
    useState(false);

  const [loadingMessageIndex, setLoadingMessageIndex] =
    useState(0);

  const [saving, setSaving] =
    useState(false);

  const [error, setError] =
    useState('');

  const [generationNotice, setGenerationNotice] =
    useState('');

  const [selectedIds, setSelectedIds] =
    useState([]);

  const [savedIds, setSavedIds] =
    useState([]);

  const fileInputRef =
    useRef(null);


  /* ============================================================
     Loading message rotation
     ============================================================ */

  useEffect(() => {
    if (!loading) {
      setLoadingMessageIndex(0);
      return undefined;
    }

    const timer = window.setInterval(() => {
      setLoadingMessageIndex(
        (index) =>
          (index + 1) %
          generationMessages.length
      );
    }, 3000);

    return () => {
      window.clearInterval(timer);
    };
  }, [loading]);


  /* ============================================================
     Open modal from Django
     ============================================================ */

  useEffect(() => {
    window.mecardOpenCardGenerator = () => {
      setIsOpen(true);
    };

    return () => {
      delete window.mecardOpenCardGenerator;
    };
  }, []);


  /* ============================================================
     Image select
     ============================================================ */

  const handleImageSelect = (event) => {
    const file =
      event.target.files?.[0] || null;

    setReferenceImage(file);

    if (referenceImagePreviewUrl) {
      URL.revokeObjectURL(
        referenceImagePreviewUrl
      );
    }

    if (file) {
      setReferenceImagePreviewUrl(
        URL.createObjectURL(file)
      );
    } else {
      setReferenceImagePreviewUrl(null);
    }
  };


  /* ============================================================
     Clear image
     ============================================================ */

  const clearImage = () => {
    setReferenceImage(null);

    if (referenceImagePreviewUrl) {
      URL.revokeObjectURL(
        referenceImagePreviewUrl
      );
    }

    setReferenceImagePreviewUrl(null);

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };


  /* ============================================================
     Generate
     ============================================================ */

  const generate = useCallback(async () => {
    if (!categorySlug || loading) {
      return;
    }

    setLoading(true);
    setError('');
    setGenerationNotice('');

    setVariants([]);
    setSelectedIds([]);
    setSavedIds([]);

    const ratio =
      orientation === 'vertical'
        ? 540 / 856
        : 856 / 540;

    try {
      const formData = new FormData();

      formData.append(
        'company_id',
        companyId
      );

      formData.append(
        'category_slug',
        categorySlug
      );

      formData.append(
        'orientation',
        orientation
      );

      formData.append(
        'variant_count',
        String(variantCount)
      );

      if (userPrompt.trim()) {
        formData.append(
          'user_prompt',
          userPrompt.trim()
        );
      }

      if (referenceImage) {
        formData.append(
          'reference_image',
          referenceImage
        );
      }

      const response = await fetch(
        '/api/cards/generate/',
        {
          method: 'POST',

          headers: {
            Accept: 'application/json',

            'X-CSRFToken':
              getCookie('csrftoken'),
          },

          credentials: 'same-origin',

          body: formData,
        }
      );

      const data =
        await readApiResponse(
          response,
          'Card generation failed.'
        );

      if (
        !Array.isArray(data.variants)
      ) {
        throw new Error(
          'The server returned an invalid card preview response.'
        );
      }

      /*
       * Make absolutely sure every variant has
       * a unique frontend ID.
       */
      const normalizedVariants =
        data.variants.map(
          (variant, index) => ({
            ...variant,

            id:
              variant.id ||
              `variant-${Date.now()}-${index}`,

            index:
              typeof variant.index === 'number'
                ? variant.index
                : index,
          })
        );

      setVariants(
        normalizedVariants
      );
      setGenerationNotice(data.generation_notice || '');

      setGeneratedAspectRatio(
        ratio
      );
    } catch (err) {
      setError(
        err?.message ||
        'Card generation failed.'
      );
    } finally {
      setLoading(false);
    }
  }, [
    companyId,
    categorySlug,
    orientation,
    variantCount,
    userPrompt,
    referenceImage,
    loading,
  ]);


  /* ============================================================
     Select / deselect variant
     ============================================================ */

  const toggleVariant = (id) => {
    setSelectedIds(
      (selected) =>
        selected.includes(id)
          ? selected.filter(
              (selectedId) =>
                selectedId !== id
            )
          : [...selected, id]
    );

    setError('');
  };


  /* ============================================================
     Save selected variants
     ============================================================ */

  const saveSelectedVariants = async () => {
    const selectedVariants = variants.filter(
      (variant) => selectedIds.includes(variant.id)
    );

    if (!selectedVariants.length || saving || savedIds.length) {
      return;
    }

    setSaving(true);
    setError('');

    try {
      const previewTokens = selectedVariants.map(
        (variant) => variant.preview_token
      );

      if (previewTokens.some((token) => !token)) {
        throw new Error(
          'A selected preview has expired or is invalid. Generate the designs again before saving.'
        );
      }

      const response = await fetch('/api/cards/save-generated/', {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        credentials: 'same-origin',
        body: JSON.stringify({ preview_tokens: previewTokens }),
      });

      await readApiResponse(
        response,
        'Could not save the selected card designs.'
      );

      setSavedIds(
        selectedVariants.map((variant) => variant.id)
      );

    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };


  /* ============================================================
     Close modal
     ============================================================ */

  const closeModal = () => {
    if (loading || saving) {
      return;
    }

    setIsOpen(false);
  };


  if (!isOpen) {
    return null;
  }


  /* ============================================================
     Render
     ============================================================ */

  return (
    <div
      onClick={closeModal}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,

        background:
          'rgba(0, 0, 0, .72)',

        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',

        padding: '4vh 24px',

        overflowY: 'auto',
      }}
    >
      <div
        onClick={(event) =>
          event.stopPropagation()
        }
        style={{
          width:
            'min(1450px, 100%)',

          maxHeight: '92vh',

          display: 'flex',
          flexDirection: 'column',

          background:
            'var(--surface)',

          border:
            '1px solid var(--line)',

          borderRadius: 16,

          boxShadow:
            '0 30px 90px rgba(0,0,0,.55)',

          overflow: 'hidden',
        }}
      >

        {/* ======================================================
            Modal Header
        ====================================================== */}

        <div
          style={{
            flex: '0 0 auto',

            display: 'flex',
            justifyContent:
              'space-between',
            alignItems: 'center',

            padding:
              '16px 22px',

            borderBottom:
              '1px solid var(--line)',
          }}
        >
          <div>
            <h2
              style={{
                margin: 0,
                color: 'var(--ink)',
                fontSize: 18,
              }}
            >
              Create Card
            </h2>

            <p
              style={{
                margin:
                  '3px 0 0',
                color:
                  'var(--muted)',
                fontSize: 11,
              }}
            >
              Generate multiple
              card designs and
              select the ones you
              want to save.
            </p>
          </div>

          <button
            type="button"
            onClick={closeModal}
            disabled={
              loading || saving
            }
            style={{
              width: 36,
              height: 36,

              border:
                '1px solid var(--line)',

              borderRadius: 8,

              background:
                'var(--surface-soft)',

              color: 'var(--ink)',

              fontSize: 24,

              lineHeight: 1,

              cursor:
                loading || saving
                  ? 'not-allowed'
                  : 'pointer',

              opacity:
                loading || saving
                  ? 0.5
                  : 1,
            }}
          >
            ×
          </button>
        </div>


        {/* ======================================================
            Scrollable Body
        ====================================================== */}

        <div
          style={{
            flex: '1 1 auto',

            minHeight: 0,

            overflowY: 'auto',

            padding: 22,
          }}
        >

          {/* ====================================================
              Controls
          ==================================================== */}

          <div
            style={{
              display: 'grid',

              gridTemplateColumns:
                'minmax(220px, 1fr) 130px 170px minmax(260px, 2fr)',

              gap: 14,

              marginBottom: 16,
            }}
          >

            {/* Category */}

            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 700,
                  color:
                    'var(--ink)',
                }}
              >
                Card category
              </label>

              <select
                value={categorySlug}
                onChange={(event) =>
                  setCategorySlug(
                    event.target.value
                  )
                }
                disabled={
                  loading || saving
                }
                style={{
                  width: '100%',
                  minHeight: 42,

                  border:
                    '1px solid var(--line)',

                  borderRadius: 8,

                  background:
                    'var(--surface-soft)',

                  color:
                    'var(--ink)',

                  padding:
                    '0 10px',
                }}
              >
                {categories.map(
                  (category) => (
                    <option
                      key={
                        category.slug
                      }
                      value={
                        category.slug
                      }
                    >
                      {category.name}
                    </option>
                  )
                )}
              </select>
            </div>


            {/* Variants */}

            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 700,
                  color:
                    'var(--ink)',
                }}
              >
                Variants
              </label>

              <select
                value={variantCount}
                onChange={(event) =>
                  setVariantCount(
                    Number(
                      event.target.value
                    )
                  )
                }
                disabled={
                  loading || saving
                }
                style={{
                  width: '100%',
                  minHeight: 42,

                  border:
                    '1px solid var(--line)',

                  borderRadius: 8,

                  background:
                    'var(--surface-soft)',

                  color:
                    'var(--ink)',

                  padding:
                    '0 10px',
                }}
              >
                {[1, 2, 3, 4, 5, 6].map(
                  (number) => (
                    <option
                      key={number}
                      value={number}
                    >
                      {number}
                    </option>
                  )
                )}
              </select>
            </div>


            {/* Orientation */}

            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 700,
                  color:
                    'var(--ink)',
                }}
              >
                Orientation
              </label>

              <select
                value={orientation}
                onChange={(event) =>
                  setOrientation(
                    event.target.value
                  )
                }
                disabled={
                  loading || saving
                }
                style={{
                  width: '100%',
                  minHeight: 42,

                  border:
                    '1px solid var(--line)',

                  borderRadius: 8,

                  background:
                    'var(--surface-soft)',

                  color:
                    'var(--ink)',

                  padding:
                    '0 10px',
                }}
              >
                <option value="horizontal">
                  Horizontal
                </option>

                <option value="vertical">
                  Vertical
                </option>
              </select>
            </div>


            {/* Prompt */}

            <div>
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 700,
                  color:
                    'var(--ink)',
                }}
              >
                Design instructions
                (optional)
              </label>

              <input
                type="text"
                value={userPrompt}
                onChange={(event) =>
                  setUserPrompt(
                    event.target.value
                  )
                }
                disabled={
                  loading || saving
                }
                placeholder="e.g. premium, minimal, rounded corners"
                style={{
                  width: '100%',
                  minHeight: 42,

                  boxSizing:
                    'border-box',

                  border:
                    '1px solid var(--line)',

                  borderRadius: 8,

                  background:
                    'var(--surface-soft)',

                  color:
                    'var(--ink)',

                  padding:
                    '0 12px',
                }}
              />
            </div>
          </div>


          {/* ====================================================
              Reference Image
          ==================================================== */}

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,

              marginBottom: 20,

              padding:
                '12px 14px',

              border:
                '1px solid var(--line)',

              borderRadius: 10,

              background:
                'var(--surface-soft)',
            }}
          >
            <div
              style={{
                flex: 1,
              }}
            >
              <label
                style={{
                  display: 'block',
                  marginBottom: 6,
                  fontSize: 13,
                  fontWeight: 700,
                  color:
                    'var(--ink)',
                }}
              >
                Reference image
              </label>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={
                  handleImageSelect
                }
                disabled={
                  loading || saving
                }
                style={{
                  fontSize: 12,
                  color:
                    'var(--muted)',
                }}
              />

              <p
                style={{
                  margin:
                    '6px 0 0',

                  fontSize: 11,

                  color:
                    'var(--muted)',
                }}
              >
                The AI will use this
                image as the design
                reference for layout,
                spacing, typography,
                shapes and colors. Each
                result will follow a
                different card shown
                in the reference, when
                available.
              </p>
            </div>


            {referenceImagePreviewUrl && (
              <>
                <img
                  src={
                    referenceImagePreviewUrl
                  }
                  alt="Reference"
                  style={{
                    width: 80,
                    height: 80,

                    objectFit: 'cover',

                    borderRadius: 8,

                    border:
                      '1px solid var(--line)',
                  }}
                />

                <button
                  type="button"
                  onClick={clearImage}
                  disabled={
                    loading || saving
                  }
                  style={{
                    border: 0,
                    background:
                      'transparent',

                    color:
                      'var(--muted)',

                    cursor: 'pointer',

                    fontSize: 11,
                    fontWeight: 700,

                    textDecoration:
                      'underline',
                  }}
                >
                  Remove
                </button>
              </>
            )}


            <button
              type="button"
              onClick={generate}
              disabled={
                loading ||
                saving ||
                !categorySlug
              }
              className="primary-action"
              style={{
                minWidth: 110,

                opacity:
                  loading ||
                  saving
                    ? 0.6
                    : 1,
              }}
            >
              {loading
                ? 'Designing…'
                : 'Generate'}
            </button>
          </div>


          {/* ====================================================
              Loading
          ==================================================== */}

          {loading && (
            <div
              className="ai-wait-panel ai-wait-panel--card"
              role="status"
              aria-live="polite"
              style={{
                marginBottom: 20,
              }}
            >
              <div
                className="ai-wait-art"
                aria-hidden="true"
              >
                <span className="ai-wait-art__orbit ai-wait-art__orbit--one"></span>

                <span className="ai-wait-art__orbit ai-wait-art__orbit--two"></span>

                <div className="ai-wait-art__card">
                  <span className="ai-wait-art__card-mark"></span>
                  <span className="ai-wait-art__card-line"></span>
                  <span className="ai-wait-art__card-line ai-wait-art__card-line--short"></span>
                </div>

                <span className="ai-wait-art__spark ai-wait-art__spark--one">
                  ✦
                </span>

                <span className="ai-wait-art__spark ai-wait-art__spark--two">
                  ✧
                </span>
              </div>

              <div className="ai-wait-copy">
                <span className="ai-wait-badge">
                  <span></span>
                  AI at work
                </span>

                <h3>
                  Designing your cards
                </h3>

                <p>
                  {
                    generationMessages[
                      loadingMessageIndex
                    ]
                  }
                  …
                </p>

                <span className="ai-wait-note">
                  Creating {variantCount}{' '}
                  distinct designs.
                </span>
              </div>
            </div>
          )}


          {/* ====================================================
              Error
          ==================================================== */}

          {error && (
            <div
              style={{
                marginBottom: 18,

                border:
                  '1px solid #e6a6a6',

                borderRadius: 8,

                padding:
                  '10px 12px',

                color: '#9a3030',

                background:
                  '#fff1f1',

                fontSize: 12,
              }}
            >
              {error}
            </div>
          )}

          {generationNotice && (
            <div
              role="status"
              style={{
                marginBottom: 18,
                border: '1px solid #e8c979',
                borderRadius: 8,
                padding: '10px 12px',
                color: '#73530b',
                background: '#fff8df',
                fontSize: 12,
              }}
            >
              {generationNotice}
            </div>
          )}


          {/* ====================================================
              Variants
          ==================================================== */}

          {variants.length > 0 && (
            <>
              <div
                style={{
                  display: 'grid',

                  gridTemplateColumns:
                    `repeat(${Math.min(
                      variants.length,
                      3
                    )}, minmax(0, 1fr))`,

                  gap: 16,

                  borderTop:
                    '1px solid var(--line)',

                  paddingTop: 20,
                }}
              >
                {variants.map(
                  (card, index) => (
                    <VariantCard
                      key={card.id}
                      card={card}
                      index={index}
                      isSelected={selectedIds.includes(
                        card.id
                      )}
                      onToggle={
                        toggleVariant
                      }
                      aspectRatio={
                        generatedAspectRatio
                      }
                      disabled={
                        saving ||
                        savedIds.length > 0
                      }
                    />
                  )
                )}
              </div>


              {/* ==================================================
                  Save bar
              ================================================== */}

              <div
                style={{
                  display: 'flex',

                  alignItems: 'center',

                  justifyContent:
                    'space-between',

                  gap: 16,

                  marginTop: 18,

                  paddingTop: 16,

                  borderTop:
                    '1px solid var(--line)',
                }}
              >
                <p
                  style={{
                    margin: 0,
                    color:
                      'var(--muted)',
                    fontSize: 12,
                  }}
                >
                  {savedIds.length
                    ? `${savedIds.length} ${
                        savedIds.length === 1
                          ? 'design has'
                          : 'designs have'
                      } been saved.`
                    : selectedIds.length
                    ? `${selectedIds.length} ${
                        selectedIds.length === 1
                          ? 'design'
                          : 'designs'
                      } selected.`
                    : 'Select one or more designs to save.'}
                </p>

                <button
                  type="button"
                  onClick={
                    saveSelectedVariants
                  }
                  disabled={
                    !selectedIds.length ||
                    saving ||
                    savedIds.length > 0
                  }
                  className="primary-action"
                  style={{
                    opacity:
                      !selectedIds.length ||
                      saving ||
                      savedIds.length > 0
                        ? 0.6
                        : 1,

                    whiteSpace:
                      'nowrap',
                  }}
                >
                  {savedIds.length
                    ? 'Saved'
                    : saving
                    ? 'Saving…'
                    : `Save selected card${
                        selectedIds.length ===
                        1
                          ? ''
                          : 's'
                      }${
                        selectedIds.length
                          ? ` (${selectedIds.length})`
                          : ''
                      }`}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}


/* ============================================================
   Bootstrap React
   ============================================================ */

const rootEl =
  document.getElementById(
    'card-generator-root'
  );

if (rootEl) {
  const companyId =
    rootEl.getAttribute(
      'data-company-id'
    );

  const categoriesDataEl =
    document.getElementById(
      'card-categories-data'
    );

  let initialCategories = [];

  try {
    initialCategories =
      categoriesDataEl
        ? JSON.parse(
            categoriesDataEl.textContent
          )
        : [];
  } catch (error) {
    console.error(
      'Unable to parse card categories:',
      error
    );
  }

  ReactDOM
    .createRoot(rootEl)
    .render(
      <CardGeneratorApp
        companyId={companyId}
        initialCategories={
          initialCategories
        }
      />
    );
}
