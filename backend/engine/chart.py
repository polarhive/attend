import logging
import matplotlib.pyplot as plt
import numpy as np
import base64
from io import BytesIO
from backend.engine.attendance import AttendanceCalculator

def generate_graph(attendance_data, threshold, subject_mapping: dict):
    subjects, attended, total, skipped, threshold_marks = [], [], [], [], []

    for item in attendance_data:
        # Use branch-specific subject mapping; if a subject isn't mapped, fall back to the original value.
        subject_name = subject_mapping.get(item[0], item[0])
        attended_classes, total_classes = map(int, item[2].split("/"))
        skipped.append(total_classes - attended_classes)
        subjects.append(subject_name)
        attended.append(attended_classes)
        total.append(total_classes)
        threshold_marks.append(AttendanceCalculator.calculate_threshold_mark(total_classes, threshold))

    plt.figure(figsize=(12, 8))
    x = np.arange(len(subjects))
    plt.bar(x, attended, color='seagreen')
    plt.bar(x, skipped, bottom=attended, color='firebrick')

    for i in range(len(subjects)):
        plt.text(x[i], threshold_marks[i] + 1, f"{threshold}%: {threshold_marks[i]}", ha='center', fontsize=9)

    new_labels = [f"{sub}\n{att}/{tot}" for sub, att, tot in zip(subjects, attended, total)]
    plt.xticks(x, new_labels, rotation=45, ha="right")
    plt.xlabel("Subjects")
    plt.ylabel("Classes")
    plt.title(f"Attendance ({threshold}% Threshold)")
    plt.legend(["Attended", "Skipped"])
    plt.tight_layout()

    buf = BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)

    return base64.b64encode(buf.getvalue()).decode("utf-8")
