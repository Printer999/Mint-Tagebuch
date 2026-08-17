const weekDays = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"];
const STORAGE_KEY = "mint-week-temp-diary-v1";

let selectedDay = weekDays[0];

const dayTabs = document.getElementById("day-tabs");
const selectedDayLabel = document.getElementById("selected-day-label");
const listHeader = document.getElementById("list-header");
const avgRating = document.getElementById("avg-rating");
const totalEntries = document.getElementById("total-entries");
const dateRange = document.getElementById("date-range");
const activeDayName = document.getElementById("active-day-name");
const activeDayCount = document.getElementById("active-day-count");
const latestEntryDate = document.getElementById("latest-entry-date");
const latestEntryPreview = document.getElementById("latest-entry-preview");
const entriesList = document.getElementById("entries-list");
const entryForm = document.getElementById("entry-form");
const entryDateInput = document.getElementById("entry-date");
const highLightInput = document.getElementById("high-light");
const lowLightInput = document.getElementById("low-light");
const notesInput = document.getElementById("notes");

function getDefaultData() {
  return weekDays.reduce((acc, day) => {
    acc[day] = [];
    return acc;
  }, {});
}

function loadEntries() {
  const saved = localStorage.getItem(STORAGE_KEY);

  if (!saved) {
    const defaultData = getDefaultData();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(defaultData));
    return defaultData;
  }

  try {
    const parsed = JSON.parse(saved);
    return { ...getDefaultData(), ...parsed };
  } catch (error) {
    console.error("Fehler beim Laden der Tagebucheinträge:", error);
    const fallback = getDefaultData();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fallback));
    return fallback;
  }
}

function saveEntries(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function getDayEntries() {
  const data = loadEntries();
  return data[selectedDay] || [];
}

function updateRatingState() {
  const ratingInputs = Array.from(document.querySelectorAll('.rating-picker input[name="rating"]'));
  const selectedValue = Number(ratingInputs.find((input) => input.checked)?.value || 0);

  ratingInputs.forEach((input) => {
    const label = input.nextElementSibling;
    if (label) {
      label.classList.toggle("selected", Number(input.value) <= selectedValue);
    }
  });
}

function renderDayTabs() {
  dayTabs.innerHTML = "";

  weekDays.forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `day-tab ${day === selectedDay ? "active" : ""}`;
    button.textContent = day;
    button.setAttribute("aria-pressed", String(day === selectedDay));

    button.addEventListener("click", () => {
      selectedDay = day;
      render();
    });

    dayTabs.appendChild(button);
  });
}

function renderSummary() {
  const data = loadEntries();
  const allEntries = weekDays.flatMap((day) => data[day] || []);
  const total = allEntries.length;
  const avg = total > 0 ? allEntries.reduce((sum, item) => sum + Number(item.rating), 0) / total : 0;

  avgRating.textContent = `${avg.toFixed(1)}/5`;
  totalEntries.textContent = String(total);

  const dates = allEntries.map((item) => item.entry_date).filter(Boolean);
  const first = dates.length ? new Date(Math.min(...dates.map((date) => new Date(date).getTime()))) : null;
  const last = dates.length ? new Date(Math.max(...dates.map((date) => new Date(date).getTime()))) : null;

  if (first && last) {
    const format = (date) => date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
    dateRange.textContent = `${format(first)} – ${format(last)}`;
  } else {
    dateRange.textContent = "Noch keine Daten";
  }

  activeDayName.textContent = selectedDay;
  activeDayCount.textContent = `${getDayEntries().length} ${getDayEntries().length === 1 ? "Eintrag" : "Einträge"}`;

  const latest = allEntries.slice().sort((a, b) => new Date(b.entry_date) - new Date(a.entry_date))[0];

  if (latest) {
    latestEntryDate.textContent = latest.entry_date;
    latestEntryPreview.textContent = latest.high_light.slice(0, 40) || "Letzter Eintrag";
  } else {
    latestEntryDate.textContent = "—";
    latestEntryPreview.textContent = "Noch keine Einträge";
  }
}

function renderEntries() {
  const entries = getDayEntries();
  selectedDayLabel.textContent = `${selectedDay}`;
  listHeader.textContent = `Einträge für ${selectedDay}`;

  if (entries.length === 0) {
    entriesList.innerHTML = '<div class="empty-state">Noch keine Einträge für diesen Tag. Füge deinen ersten Eintrag hinzu.</div>';
    return;
  }

  entriesList.innerHTML = entries
    .slice()
    .reverse()
    .map(
      (entry) => `
        <article class="entry-card">
          <div class="entry-topline">
            <strong>${entry.entry_date || "Ohne Datum"}</strong>
            <span class="rating-pill">${entry.rating}/5</span>
          </div>
          <div class="entry-fields">
            <div>
              <label>High Light</label>
              <p>${escapeHtml(entry.high_light)}</p>
            </div>
            <div>
              <label>Low Light</label>
              <p>${escapeHtml(entry.low_light)}</p>
            </div>
            ${entry.notes ? `<div><label>Notizen</label><p>${escapeHtml(entry.notes)}</p></div>` : ""}
          </div>
        </article>
      `
    )
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function render() {
  renderDayTabs();
  renderSummary();
  renderEntries();
  updateRatingState();
}

entryDateInput.value = new Date().toISOString().split("T")[0];

entryForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const entryDate = entryDateInput.value;
  const highLight = highLightInput.value.trim();
  const lowLight = lowLightInput.value.trim();
  const notes = notesInput.value.trim();
  const rating = Number(document.querySelector('.rating-picker input[name="rating"]:checked')?.value || 3);

  if (!entryDate || !highLight || !lowLight) {
    if (!entryDate) entryDateInput.focus();
    else if (!highLight) highLightInput.focus();
    else lowLightInput.focus();
    return;
  }

  const data = loadEntries();
  data[selectedDay].push({
    id: Date.now(),
    entry_date: entryDate,
    high_light: highLight,
    low_light: lowLight,
    notes,
    rating,
  });

  saveEntries(data);
  entryForm.reset();
  document.getElementById("rating-3").checked = true;
  entryDateInput.value = new Date().toISOString().split("T")[0];
  render();
});

document.querySelectorAll('.rating-picker input[name="rating"]').forEach((input) => {
  input.addEventListener("change", updateRatingState);
});

render();
