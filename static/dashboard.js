"use strict";

const state = {
    data: null,
    charts: {},
    memuat: false,
    filter: {
        status: "aktif",
        tipe: "semua",
        cari: "",
    },
};

const WARNA = {
    piutang: "#0f766e",
    piutangMuda: "rgba(15, 118, 110, 0.76)",
    utang: "#c2410c",
    utangMuda: "rgba(194, 65, 12, 0.72)",
    saldo: "#2457d6",
    dibayar: "#7c3aed",
    grid: "#edf3f1",
    teks: "#64736f",
};

const rupiah = new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0,
});

const rupiahSingkat = new Intl.NumberFormat("id-ID", {
    notation: "compact",
    maximumFractionDigits: 1,
});

function formatRupiah(nilai) {
    return rupiah.format(Number(nilai) || 0);
}

function formatRupiahSingkat(nilai) {
    return `Rp${rupiahSingkat.format(Number(nilai) || 0)}`;
}

function formatTanggal(iso) {
    if (!iso) {
        return "-";
    }
    const [tahun, bulan, hari] = iso.split("-").map(Number);
    return new Date(tahun, bulan - 1, hari).toLocaleDateString("id-ID", {
        day: "2-digit",
        month: "short",
        year: "numeric",
    });
}

function formatBulan(iso) {
    const [tahun, bulan] = iso.split("-").map(Number);
    return new Date(tahun, bulan - 1, 1).toLocaleDateString("id-ID", {
        month: "short",
        year: "numeric",
    });
}

function setTeks(id, teks) {
    const elemen = document.getElementById(id);
    if (elemen) {
        elemen.textContent = teks;
    }
}

function setStatus(teks, error = false) {
    const elemen = document.getElementById("status-perbarui");
    if (!elemen) {
        return;
    }
    elemen.textContent = teks;
    elemen.classList.toggle("is-error", error);
}

function buatElemen(tag, kelas, teks) {
    const elemen = document.createElement(tag);
    if (kelas) {
        elemen.className = kelas;
    }
    if (teks !== undefined) {
        elemen.textContent = teks;
    }
    return elemen;
}

function labelTipe(tipe) {
    return tipe === "piutang" ? "Piutang" : "Utang";
}

function labelTempo(catatan) {
    if (catatan.status === "lunas") {
        return "Sudah lunas";
    }
    if (!catatan.jatuh_tempo) {
        return "Tanpa jatuh tempo";
    }
    if (catatan.telat_hari > 0) {
        return `Telat ${catatan.telat_hari} hari`;
    }
    const sekarang = new Date();
    sekarang.setHours(0, 0, 0, 0);
    const [tahun, bulan, hari] = catatan.jatuh_tempo.split("-").map(Number);
    const tempo = new Date(tahun, bulan - 1, hari);
    const selisih = Math.round((tempo - sekarang) / 86400000);
    if (selisih === 0) {
        return "Jatuh tempo hari ini";
    }
    if (selisih > 0 && selisih <= 30) {
        return `${selisih} hari lagi`;
    }
    return formatTanggal(catatan.jatuh_tempo);
}

function tooltipRupiah(context) {
    let nilai = context.parsed;
    if (nilai && typeof nilai === "object") {
        nilai = nilai.x ?? nilai.y ?? 0;
    }
    const label = context.dataset && context.dataset.label
        ? `${context.dataset.label}: `
        : "";
    return `${label}${formatRupiah(nilai)}`;
}

function renderRingkasan(ringkasan) {
    setTeks("ringkasan-piutang", formatRupiah(ringkasan.piutang_aktif));
    setTeks("ringkasan-utang", formatRupiah(ringkasan.utang_aktif));
    setTeks("ringkasan-saldo", formatRupiah(ringkasan.saldo_bersih));
    setTeks("ringkasan-dibayar", formatRupiah(ringkasan.total_dibayar));
    setTeks(
        "ringkasan-catatan",
        `${ringkasan.jumlah_aktif} aktif · ${ringkasan.jumlah_lunas} lunas`
    );

    const badgeTelat = document.getElementById("ringkasan-telat");
    if (badgeTelat) {
        badgeTelat.textContent = `${ringkasan.jumlah_telat} telat`;
        badgeTelat.className = `badge ${
            ringkasan.jumlah_telat > 0 ? "badge-telat" : "badge-netral"
        }`;
        badgeTelat.hidden = false;
    }
}

function destroyChart(key) {
    if (state.charts[key]) {
        state.charts[key].destroy();
        delete state.charts[key];
    }
}

function aturKosong(key, canvasId, emptyId, kosong) {
    const canvas = document.getElementById(canvasId);
    const empty = document.getElementById(emptyId);
    if (!canvas || !empty) {
        return;
    }
    if (kosong) {
        destroyChart(key);
        canvas.hidden = true;
        empty.hidden = false;
    } else {
        canvas.hidden = false;
        empty.hidden = true;
    }
}

function tampilkanChart(key, canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
        return;
    }
    if (state.charts[key]) {
        state.charts[key].data = config.data;
        state.charts[key].update("none");
        return;
    }
    state.charts[key] = new Chart(canvas, config);
}

function renderChartNama(rows) {
    aturKosong("nama", "chart-nama", "chart-nama-empty", rows.length === 0);
    if (rows.length === 0) {
        return;
    }

    const nama = [...new Set(rows.map((row) => row.nama))];
    const piutang = nama.map((label) =>
        rows
            .filter((row) => row.nama === label && row.tipe === "piutang")
            .reduce((total, row) => total + row.sisa, 0)
    );
    const utang = nama.map((label) =>
        rows
            .filter((row) => row.nama === label && row.tipe === "utang")
            .reduce((total, row) => total + row.sisa, 0)
    );

    tampilkanChart("nama", "chart-nama", {
        type: "bar",
        data: {
            labels: nama,
            datasets: [
                {
                    label: "Piutang",
                    data: piutang,
                    backgroundColor: WARNA.piutangMuda,
                    borderRadius: 6,
                    maxBarThickness: 28,
                },
                {
                    label: "Utang",
                    data: utang,
                    backgroundColor: WARNA.utangMuda,
                    borderRadius: 6,
                    maxBarThickness: 28,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 250 },
            indexAxis: "y",
            plugins: {
                legend: {
                    position: "top",
                    labels: {
                        usePointStyle: true,
                        boxWidth: 8,
                        boxHeight: 8,
                        padding: 14,
                    },
                },
                tooltip: { callbacks: { label: tooltipRupiah } },
            },
            scales: {
                x: {
                    beginAtZero: true,
                    border: { display: false },
                    grid: { color: WARNA.grid },
                    ticks: { callback: (nilai) => formatRupiahSingkat(nilai) },
                },
                y: {
                    border: { display: false },
                    grid: { display: false },
                },
            },
        },
    });
}

function renderChartKomposisi(ringkasan) {
    const kosong =
        ringkasan.piutang_aktif === 0 && ringkasan.utang_aktif === 0;
    aturKosong(
        "komposisi",
        "chart-komposisi",
        "chart-komposisi-empty",
        kosong
    );
    if (kosong) {
        return;
    }

    tampilkanChart("komposisi", "chart-komposisi", {
        type: "doughnut",
        data: {
            labels: ["Piutang", "Utang"],
            datasets: [
                {
                    data: [ringkasan.piutang_aktif, ringkasan.utang_aktif],
                    backgroundColor: [WARNA.piutang, WARNA.utang],
                    borderColor: "#ffffff",
                    borderWidth: 3,
                    hoverOffset: 6,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "68%",
            animation: { duration: 250 },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: {
                        usePointStyle: true,
                        boxWidth: 8,
                        boxHeight: 8,
                        padding: 16,
                    },
                },
                tooltip: { callbacks: { label: tooltipRupiah } },
            },
        },
    });
}

function renderChartBulanan(rows) {
    const adaPembayaran = rows.some((row) => row.total > 0);
    aturKosong(
        "bulanan",
        "chart-bulanan",
        "chart-bulanan-empty",
        !adaPembayaran
    );
    if (!adaPembayaran) {
        return;
    }

    tampilkanChart("bulanan", "chart-bulanan", {
        type: "line",
        data: {
            labels: rows.map((row) => formatBulan(row.bulan)),
            datasets: [
                {
                    label: "Pembayaran",
                    data: rows.map((row) => row.total),
                    borderColor: WARNA.saldo,
                    backgroundColor: "rgba(36, 87, 214, 0.12)",
                    fill: true,
                    tension: 0.34,
                    borderWidth: 2,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: WARNA.saldo,
                    pointBorderColor: "#ffffff",
                    pointBorderWidth: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 250 },
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: tooltipRupiah } },
            },
            scales: {
                x: {
                    border: { display: false },
                    grid: { display: false },
                    ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
                },
                y: {
                    beginAtZero: true,
                    border: { display: false },
                    grid: { color: WARNA.grid },
                    ticks: { callback: (nilai) => formatRupiahSingkat(nilai) },
                },
            },
        },
    });
}

function renderCharts(data) {
    if (typeof Chart === "undefined") {
        setStatus("Grafik gagal dimuat.", true);
        return;
    }
    renderChartNama(data.grafik.per_nama);
    renderChartKomposisi(data.ringkasan);
    renderChartBulanan(data.grafik.bulanan);
}

function renderDaftarTempo(items, containerId, telat = false) {
    const container = document.getElementById(containerId);
    if (!container) {
        return;
    }
    container.replaceChildren();

    if (items.length === 0) {
        container.append(
            buatElemen(
                "p",
                "empty-note",
                telat
                    ? "Tidak ada catatan telat."
                    : "Belum ada jatuh tempo terdekat."
            )
        );
        return;
    }

    for (const catatan of items) {
        const item = buatElemen(
            "article",
            `attention-item${telat ? " is-telat" : ""}`
        );
        const utama = buatElemen("div", "attention-main");
        utama.append(buatElemen("strong", "", catatan.nama));
        utama.append(
            buatElemen(
                "span",
                "attention-meta",
                `${labelTipe(catatan.tipe)} · ${labelTempo(catatan)}`
            )
        );

        const jumlah = buatElemen("div", "attention-amount");
        jumlah.append(buatElemen("span", "", formatRupiah(catatan.sisa)));
        jumlah.append(buatElemen("small", "", "sisa"));

        item.append(utama, jumlah);
        container.append(item);
    }
}

function renderPembayaran(items) {
    const container = document.getElementById("daftar-pembayaran");
    if (!container) {
        return;
    }
    container.replaceChildren();

    if (items.length === 0) {
        container.append(buatElemen("p", "empty-note", "Belum ada pembayaran."));
        return;
    }

    for (const pembayaran of items) {
        const item = buatElemen("div", "payment-item");
        const utama = buatElemen("div", "payment-main");
        utama.append(buatElemen("strong", "", pembayaran.nama));
        utama.append(
            buatElemen(
                "span",
                "",
                `${labelTipe(pembayaran.tipe)} · ${formatTanggal(
                    pembayaran.tanggal
                )}`
            )
        );
        item.append(
            utama,
            buatElemen(
                "div",
                "payment-amount",
                formatRupiah(pembayaran.jumlah)
            )
        );
        container.append(item);
    }
}

function renderStatus(catatan) {
    const sel = document.createElement("td");
    const status = buatElemen(
        "span",
        `badge ${catatan.status === "lunas" ? "badge-lunas" : "badge-aktif"}`,
        catatan.status === "lunas" ? "Lunas" : "Aktif"
    );
    sel.append(status);

    if (catatan.status === "aktif" && catatan.telat_hari > 0) {
        sel.append(
            buatElemen(
                "span",
                "badge badge-telat",
                `Telat ${catatan.telat_hari} hari`
            )
        );
    }
    return sel;
}

function renderTable() {
    const tbody = document.getElementById("tabel-catatan");
    if (!tbody) {
        return;
    }
    tbody.replaceChildren();

    const data = state.data ? state.data.catatan : [];
    const cari = state.filter.cari.trim().toLowerCase();
    const hasil = data.filter((catatan) => {
        const cocokStatus =
            state.filter.status === "semua" ||
            catatan.status === state.filter.status;
        const cocokTipe =
            state.filter.tipe === "semua" ||
            catatan.tipe === state.filter.tipe;
        const cocokCari =
            cari === "" ||
            catatan.nama.toLowerCase().includes(cari) ||
            (catatan.catatan || "").toLowerCase().includes(cari);
        return cocokStatus && cocokTipe && cocokCari;
    });

    setTeks(
        "jumlah-catatan",
        `${hasil.length} dari ${data.length} catatan`
    );

    if (hasil.length === 0) {
        const baris = document.createElement("tr");
        const sel = buatElemen(
            "td",
            "empty-cell",
            "Tidak ada catatan yang cocok dengan filter."
        );
        sel.colSpan = 8;
        baris.append(sel);
        tbody.append(baris);
        return;
    }

    for (const catatan of hasil) {
        const baris = document.createElement("tr");

        const id = buatElemen("td", "cell-muted", `#${catatan.id}`);
        const nama = buatElemen("td", "cell-name", catatan.nama);

        const tipeSel = document.createElement("td");
        tipeSel.append(
            buatElemen(
                "span",
                `badge ${
                    catatan.tipe === "piutang"
                        ? "badge-piutang"
                        : "badge-utang"
                }`,
                labelTipe(catatan.tipe)
            )
        );

        const jumlah = buatElemen(
            "td",
            "cell-amount",
            formatRupiah(catatan.jumlah)
        );
        const sisa = buatElemen(
            "td",
            "cell-amount",
            formatRupiah(catatan.sisa)
        );
        const tempo = buatElemen(
            "td",
            "cell-muted",
            formatTanggal(catatan.jatuh_tempo)
        );
        const status = renderStatus(catatan);

        const aksi = document.createElement("td");
        const tombol = buatElemen("button", "table-button", "Detail");
        tombol.type = "button";
        tombol.dataset.id = catatan.id;
        aksi.append(tombol);

        baris.append(id, nama, tipeSel, jumlah, sisa, tempo, status, aksi);
        tbody.append(baris);
    }
}

function detailItem(label, nilai) {
    const item = buatElemen("div", "detail-item");
    item.append(buatElemen("span", "", label));
    item.append(buatElemen("strong", "", nilai));
    return item;
}

function renderDetail(data) {
    const isi = document.getElementById("detail-isi");
    const judul = document.getElementById("detail-judul");
    if (!isi || !judul) {
        return;
    }

    const catatan = data.catatan;
    judul.textContent = `#${catatan.id} — ${catatan.nama}`;

    const fragmen = document.createDocumentFragment();
    const grid = buatElemen("div", "detail-grid");
    grid.append(
        detailItem("Tipe", labelTipe(catatan.tipe)),
        detailItem("Status", catatan.status === "lunas" ? "Lunas" : "Aktif"),
        detailItem("Jumlah", formatRupiah(catatan.jumlah)),
        detailItem("Sisa", formatRupiah(catatan.sisa)),
        detailItem("Dibuat", formatTanggal(catatan.tgl_dibuat)),
        detailItem("Jatuh tempo", formatTanggal(catatan.jatuh_tempo)),
        detailItem("Total dibayar", formatRupiah(data.total_dibayar)),
        detailItem("Keterlambatan", labelTempo(catatan))
    );
    fragmen.append(grid);

    if (catatan.catatan) {
        fragmen.append(buatElemen("p", "detail-note", catatan.catatan));
    }

    fragmen.append(buatElemen("h3", "detail-subheading", "Riwayat pembayaran"));
    if (data.pembayaran.length === 0) {
        fragmen.append(buatElemen("p", "empty-note", "Belum ada pembayaran."));
    } else {
        const wrap = buatElemen("div", "table-wrap");
        const tabel = document.createElement("table");
        const thead = document.createElement("thead");
        const headRow = document.createElement("tr");
        headRow.append(
            buatElemen("th", "", "Tanggal"),
            buatElemen("th", "", "Jumlah")
        );
        thead.append(headRow);

        const tbody = document.createElement("tbody");
        for (const pembayaran of data.pembayaran) {
            const baris = document.createElement("tr");
            baris.append(
                buatElemen("td", "", formatTanggal(pembayaran.tanggal)),
                buatElemen(
                    "td",
                    "cell-amount",
                    formatRupiah(pembayaran.jumlah)
                )
            );
            tbody.append(baris);
        }
        tabel.append(thead, tbody);
        wrap.append(tabel);
        fragmen.append(wrap);
    }

    isi.replaceChildren(fragmen);
}

async function bukaDetail(id) {
    const modal = document.getElementById("modal-detail");
    const isi = document.getElementById("detail-isi");
    const judul = document.getElementById("detail-judul");
    if (!modal || !isi || !judul) {
        return;
    }

    judul.textContent = `Catatan #${id}`;
    isi.replaceChildren(buatElemen("p", "empty-note", "Memuat detail..."));
    if (typeof modal.showModal === "function") {
        modal.showModal();
    } else {
        modal.setAttribute("open", "");
    }

    try {
        const respons = await fetch(`/api/debts/${encodeURIComponent(id)}`, {
            headers: { Accept: "application/json" },
            cache: "no-store",
        });
        if (respons.status === 401) {
            window.location.assign("/");
            return;
        }
        if (!respons.ok) {
            throw new Error(`HTTP ${respons.status}`);
        }
        renderDetail(await respons.json());
    } catch (error) {
        console.error(error);
        isi.replaceChildren(
            buatElemen("p", "empty-note", "Detail gagal dimuat.")
        );
    }
}

function render(data) {
    renderRingkasan(data.ringkasan);
    renderCharts(data);
    renderDaftarTempo(data.jatuh_tempo, "daftar-jatuh-tempo");
    renderDaftarTempo(data.telat, "daftar-telat", true);
    renderPembayaran(data.pembayaran_terbaru);
    renderTable();
}

async function muatData() {
    if (state.memuat) {
        return;
    }
    state.memuat = true;
    try {
        const respons = await fetch("/api/dashboard", {
            headers: { Accept: "application/json" },
            cache: "no-store",
        });
        if (respons.status === 401) {
            window.location.assign("/");
            return;
        }
        if (!respons.ok) {
            throw new Error(`HTTP ${respons.status}`);
        }
        const data = await respons.json();
        state.data = data;
        render(data);
        setStatus(
            `Diperbarui ${new Date().toLocaleTimeString("id-ID", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            })}`
        );
    } catch (error) {
        console.error(error);
        setStatus("Gagal memuat data. Mencoba lagi...", true);
    } finally {
        state.memuat = false;
    }
}

function pasangEvent() {
    const status = document.getElementById("filter-status");
    const tipe = document.getElementById("filter-tipe");
    const cari = document.getElementById("filter-cari");
    const refresh = document.getElementById("tombol-refresh");
    const tbody = document.getElementById("tabel-catatan");
    const modal = document.getElementById("modal-detail");
    const tutup = document.getElementById("tombol-tutup-detail");

    status?.addEventListener("change", () => {
        state.filter.status = status.value;
        renderTable();
    });
    tipe?.addEventListener("change", () => {
        state.filter.tipe = tipe.value;
        renderTable();
    });
    cari?.addEventListener("input", () => {
        state.filter.cari = cari.value;
        renderTable();
    });
    refresh?.addEventListener("click", () => muatData());
    tbody?.addEventListener("click", (event) => {
        const tombol = event.target.closest("button[data-id]");
        if (tombol) {
            bukaDetail(tombol.dataset.id);
        }
    });
    tutup?.addEventListener("click", () => modal?.close());
    modal?.addEventListener("click", (event) => {
        if (event.target === modal) {
            modal.close();
        }
    });

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) {
            muatData();
        }
    });
}

if (typeof Chart !== "undefined") {
    Chart.defaults.font.family =
        '"Segoe UI", "Inter", system-ui, -apple-system, sans-serif';
    Chart.defaults.color = WARNA.teks;
}

pasangEvent();
muatData();
setInterval(() => {
    if (!document.hidden) {
        muatData();
    }
}, 10000);
