const templates = [
  { name: "Awake", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/awake.png", dlink: "https://webglow.co.uk/freehtmltemplates/awake.zip", plink: "preview/awake/index.html" },
  { name: "CodeCraft", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/codecraft.png", dlink: "https://webglow.co.uk/freehtmltemplates/codecraft.zip", plink: "preview/codecraft/index.html" },
  { name: "Craft", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/craft.png", dlink: "https://webglow.co.uk/freehtmltemplates/craft.zip", plink: "preview/craft/index.html" },
  { name: "Nova", category: "Business", image: "https://webglow.co.uk/assets/img/templates/nova.png", dlink: "https://webglow.co.uk/freehtmltemplates/nova.zip", plink: "preview/nova/index.html" },
  { name: "Pixels", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/pixels.png", dlink: "https://webglow.co.uk/freehtmltemplates/pixels.zip", plink: "preview/pixels/index.html" },
  { name: "Polk", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/polk.png", dlink: "https://webglow.co.uk/freehtmltemplates/polk.zip", plink: "preview/polk/index.html" },
  { name: "StartUp", category: "Business", image: "https://webglow.co.uk/assets/img/templates/startup.png", dlink: "https://webglow.co.uk/freehtmltemplates/startup.zip", plink: "preview/startup/index.html" },
  { name: "Furni", category: "E-commerce", image: "https://webglow.co.uk/assets/img/templates/furni.png", dlink: "https://webglow.co.uk/freehtmltemplates/furni.zip", plink: "preview/furni/index.html" },
  { name: "Drivin", category: "Services", image: "https://webglow.co.uk/assets/img/templates/drivin.png", dlink: "https://webglow.co.uk/freehtmltemplates/drivin.zip", plink: "preview/drivin/index.html" },
  { name: "Gardener", category: "Services", image: "https://webglow.co.uk/assets/img/templates/gardener.png", dlink: "https://webglow.co.uk/freehtmltemplates/gardener.zip", plink: "preview/gardener/index.html" },
  { name: "Brber", category: "Services", image: "https://webglow.co.uk/assets/img/templates/brber.png", dlink: "https://webglow.co.uk/freehtmltemplates/brber.zip", plink: "preview/brber/index.html" },
  { name: "Accounting", category: "Business", image: "https://webglow.co.uk/assets/img/templates/accounting.png", dlink: "https://webglow.co.uk/freehtmltemplates/accounting.zip", plink: "preview/accounting/index.html" },
  { name: "Orbit", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/orbit.png", dlink: "https://webglow.co.uk/freehtmltemplates/orbit.zip", plink: "preview/orbit/index.html" },
  { name: "Nexa", category: "Business", image: "https://webglow.co.uk/assets/img/templates/nexa.png", dlink: "https://webglow.co.uk/freehtmltemplates/nexa.zip", plink: "preview/nexa/index.html" },
  { name: "Axis", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/axis.png", dlink: "https://webglow.co.uk/freehtmltemplates/axis.zip", plink: "preview/axis/index.html" },
  { name: "Savora", category: "Services", image: "https://webglow.co.uk/assets/img/templates/savora.png", dlink: "https://webglow.co.uk/freehtmltemplates/savora.zip", plink: "preview/savora/index.html" },
  { name: "eBusiness", category: "Business", image: "https://webglow.co.uk/assets/img/templates/ebusiness.png", dlink: "https://webglow.co.uk/freehtmltemplates/ebusiness.zip", plink: "preview/ebusiness/index.html" },
  { name: "Onepage", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/onepage.png", dlink: "https://webglow.co.uk/freehtmltemplates/onepage.zip", plink: "preview/onepage/index.html" },
  { name: "Delaware", category: "Business", image: "https://webglow.co.uk/assets/img/templates/delaware.png", dlink: "https://webglow.co.uk/freehtmltemplates/delaware.zip", plink: "preview/delaware/index.html" },
  { name: "RepairPlus", category: "Services", image: "https://webglow.co.uk/assets/img/templates/repairplus.png", dlink: "https://webglow.co.uk/freehtmltemplates/repairplus.zip", plink: "preview/repairplus/index.html" },
  { name: "MechanicHub", category: "Services", image: "https://webglow.co.uk/assets/img/templates/mechanichub.png", dlink: "https://webglow.co.uk/freehtmltemplates/mechanichub.zip", plink: "preview/mechanichub/index.html" },
  { name: "Stockton", category: "Business", image: "https://webglow.co.uk/assets/img/templates/stockton.png", dlink: "https://webglow.co.uk/freehtmltemplates/stockton.zip", plink: "preview/stockton/index.html" },
  { name: "Earna", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/earna.png", dlink: "https://webglow.co.uk/freehtmltemplates/earna.zip", plink: "preview/earna/index.html" },
  { name: "Binuza", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/binuza.png", dlink: "https://webglow.co.uk/freehtmltemplates/binuza.zip", plink: "preview/binuza/index.html" },
  { name: "Deconsult", category: "Services", image: "https://webglow.co.uk/assets/img/templates/deconsult.png", dlink: "https://webglow.co.uk/freehtmltemplates/deconsult.zip", plink: "preview/deconsult/index.html" },
  { name: "FingCon", category: "Business", image: "https://webglow.co.uk/assets/img/templates/fingcon.png", dlink: "https://webglow.co.uk/freehtmltemplates/fingcon.zip", plink: "preview/fingcon/index.html" },
  { name: "Consultive", category: "Business", image: "https://webglow.co.uk/assets/img/templates/consultive.png", dlink: "https://webglow.co.uk/freehtmltemplates/consultive.zip", plink: "preview/consultive/index.html" },
  { name: "Kanun", category: "Services", image: "https://webglow.co.uk/assets/img/templates/kanun.png", dlink: "https://webglow.co.uk/freehtmltemplates/kanun.zip", plink: "preview/kanun/index.html" },
  { name: "Blaxcut", category: "Services", image: "https://webglow.co.uk/assets/img/templates/blaxcut.png", dlink: "https://webglow.co.uk/freehtmltemplates/blaxcut.zip", plink: "preview/blaxcut/index.html" },
  { name: "TheBiznes", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/thebiznes.png", dlink: "https://webglow.co.uk/freehtmltemplates/thebiznes.zip", plink: "preview/thebiznes/index.html" },
  { name: "Consultar", category: "Business", image: "https://webglow.co.uk/assets/img/templates/consultar.png", dlink: "https://webglow.co.uk/freehtmltemplates/consultar.zip", plink: "preview/consultar/index.html" },
  { name: "Arcke", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/arcke.png", dlink: "https://webglow.co.uk/freehtmltemplates/arcke.zip", plink: "preview/arcke/index.html" },
  { name: "Sitech", category: "Agency", image: "https://webglow.co.uk/assets/img/templates/sitech.png", dlink: "https://webglow.co.uk/freehtmltemplates/sitech.zip", plink: "preview/sitech/index.html" },
  { name: "Cleanco", category: "Services", image: "https://webglow.co.uk/assets/img/templates/cleanco.png", dlink: "https://webglow.co.uk/freehtmltemplates/cleanco.zip", plink: "preview/cleanco/index.html" },
  { name: "Advisr", category: "Business", image: "https://webglow.co.uk/assets/img/templates/advisr.png", dlink: "https://webglow.co.uk/freehtmltemplates/advisr.zip", plink: "preview/advisr/index.html" },
  { name: "Birost", category: "Portfolio", image: "https://webglow.co.uk/assets/img/templates/birost.png", dlink: "https://webglow.co.uk/freehtmltemplates/birost.zip", plink: "preview/birost/index.html" },
];

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("templates-container");
  const filterBtns = document.querySelectorAll(".filter-btn");

  if (!container) return;

  function renderTemplates(filterStr = "All") {
    container.innerHTML = "";
    const filtered = templates.filter(t => filterStr === "All" || t.category === filterStr);

    if (filtered.length === 0) {
      container.innerHTML = "<div class='col-12 text-center py-10'><p class='text-muted'>No templates found for this category.</p></div>";
      return;
    }

    filtered.forEach((t, i) => {
      const delay = (i % 6 + 1) * 80;
      const cardHtml = `
        <div class="col-md-6 col-lg-4 mb-8 template-card" style="animation-delay: ${delay}ms;">
          <div class="work d-flex flex-column gap-3 h-100">
            <div class="work-img position-relative overflow-hidden rounded-2 border shadow-sm">
              <img
                src="${t.image}"
                alt="${t.name} - Free Website Template"
                class="img-fluid w-100 object-fit-cover"
                style="height: 220px;"
                loading="lazy"
                onerror="this.onerror=null;this.src='https://picsum.photos/seed/${t.name.toLowerCase()}/600/400';"
              >
              <div class="work-overlay d-flex align-items-center justify-content-center">
                <a href="${t.plink}" target="_blank"
                   class="btn btn-primary btn-sm px-4 py-2 rounded-pill hstack gap-2 shadow"
                   title="Live Preview">
                  <iconify-icon icon="solar:eye-linear" class="fs-5"></iconify-icon> Preview
                </a>
              </div>
            </div>
            <div class="work-details d-flex flex-column gap-2">
              <div class="hstack justify-content-between align-items-center">
                <a href="${t.plink}" target="_blank" class="text-decoration-none">
                  <h4 class="mb-0 work-title text-dark">${t.name}</h4>
                </a>
                <span class="badge text-dark border bg-light">${t.category}</span>
              </div>
              <div class="d-flex gap-2">
                <a href="${t.plink}" target="_blank" class="btn btn-sm btn-primary flex-fill py-2 rounded-pill d-flex align-items-center justify-content-center gap-1">
                  Live Preview <iconify-icon icon="solar:eye-linear"></iconify-icon>
                </a>
                <a href="${t.dlink}" class="btn btn-sm btn-outline-dark flex-fill py-2 rounded-pill d-flex align-items-center justify-content-center gap-1">
                  Download <iconify-icon icon="solar:download-square-linear"></iconify-icon>
                </a>
              </div>
            </div>
          </div>
        </div>
      `;
      container.innerHTML += cardHtml;
    });

    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
  }

  function updateTitle(filterStr) {
    const titleEl = document.getElementById("template-section-title");
    const heroTitleEl = document.getElementById("hero-title");
    const heroDescEl = document.getElementById("hero-description");
    const breadcrumbEl = document.getElementById("breadcrumb-category");

    const categoryData = {
      "All": {
        title: 'Browse Our <em class="font-instrument fw-normal"> Website Templates</em>',
        desc: "Explore our collection of high-quality, free HTML templates. Whether you're building a business site, portfolio, or store, we have the perfect design to help you get started immediately."
      },
      "Business": {
        title: 'Professional <em class="font-instrument fw-normal"> Business Templates</em>',
        desc: "Strategic designs for corporate, startup, and small business websites. Build a professional online presence with ease."
      },
      "Agency": {
        title: 'Modern <em class="font-instrument fw-normal"> Agency Layouts</em>',
        desc: "Creative and high-impact designs for marketing, design, and digital agencies to showcase their best work."
      },
      "Portfolio": {
        title: 'Stunning <em class="font-instrument fw-normal"> Portfolio Designs</em>',
        desc: "Minimalist and elegant layouts to showcase your creative work, skills, and personal brand to the world."
      },
      "E-commerce": {
        title: 'Powerful <em class="font-instrument fw-normal"> E-commerce Storefronts</em>',
        desc: "Beautiful store layouts designed to drive sales, showcase your products, and provide a seamless shopping experience."
      },
      "Services": {
        title: 'Professional <em class="font-instrument fw-normal"> Service Templates</em>',
        desc: "Functional and reliable designs for photographers, doctors, consultants, and all service-based professionals."
      }
    };

    const data = categoryData[filterStr] || categoryData["All"];

    if (heroTitleEl) heroTitleEl.innerHTML = data.title;
    if (heroDescEl) heroDescEl.textContent = data.desc;
    if (breadcrumbEl) breadcrumbEl.textContent = filterStr === "All" ? "Templates" : filterStr;

    if (titleEl) {
      if (filterStr === "All") {
        titleEl.innerHTML = `View Our Template <em class="font-instrument">Selection</em>`;
      } else {
        titleEl.innerHTML = `View Our <em class="font-instrument">${filterStr} Templates</em>`;
      }
    }
  }

  function updateActiveButton(filterStr) {
    filterBtns.forEach(btn => {
      if (btn.getAttribute("data-filter") === filterStr) {
        btn.classList.add("filter-btn-active");
        btn.classList.remove("filter-btn-dark");
      } else {
        btn.classList.add("filter-btn-dark");
        btn.classList.remove("filter-btn-active");
      }
    });
  }

  // Initial Logic
  const params = new URLSearchParams(window.location.search);
  const initialFilter = params.get('category') || "All";

  renderTemplates(initialFilter);
  updateTitle(initialFilter);
  updateActiveButton(initialFilter);

  // Unified Event Listener for Buttons and Links
  filterBtns.forEach(btn => {
    btn.addEventListener("click", e => {
      const filterValue = btn.getAttribute("data-filter");
      const isTemplatesPage = window.location.pathname.includes("templates.html");

      if (isTemplatesPage) {
        e.preventDefault();

        // Update URL
        const newUrl = new URL(window.location);
        newUrl.searchParams.set('category', filterValue);
        window.history.pushState({ category: filterValue }, "", newUrl);

        // Update UI
        renderTemplates(filterValue);
        updateTitle(filterValue);
        updateActiveButton(filterValue);

        // Scroll
        const target = document.getElementById("work");
        if (target) window.scrollTo({ top: target.offsetTop - 100, behavior: "smooth" });
      }
      // If not on templates.html, the <a> link will naturally navigate with ?category=...
    });
  });

  window.addEventListener('popstate', (e) => {
    const filter = (e.state && e.state.category) || new URLSearchParams(window.location.search).get('category') || "All";
    renderTemplates(filter);
    updateTitle(filter);
    updateActiveButton(filter);
  });
});


