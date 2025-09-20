document.getElementById("extractBtn").addEventListener("click", async () => {
  const notes = document.getElementById("notes").value;
  const resultsDiv = document.getElementById("results");

  resultsDiv.innerHTML = "<p>Processing...</p>";

  try {
    const response = await fetch("http://127.0.0.1:5000/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes }),
    });

    if (!response.ok) throw new Error("Server error");

    const data = await response.json();
    const items = data.items;

    if (items.length === 0) {
      resultsDiv.innerHTML = "<p>No action items found.</p>";
      return;
    }

    let html =
      "<table><tr><th>Action</th><th>Assignee</th><th>Deadline</th></tr>";
    items.forEach((item) => {
      html += `<tr>
                        <td>${item.action}</td>
                        <td>${item.assignee}</td>
                        <td>${item.deadline}</td>
                     </tr>`;
    });
    html += "</table>";

    resultsDiv.innerHTML = html;
  } catch (err) {
    console.error(err);
    resultsDiv.innerHTML =
      "<p style='color:red;'>Cannot reach Flask server. Make sure it is running.</p>";
  }
});
