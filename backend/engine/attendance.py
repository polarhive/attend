class AttendanceCalculator:
    @staticmethod
    def calculate_bunkable(total_classes, attended_classes, threshold):
        """
        Calculate the maximum number of bunkable classes given the threshold.
        """
        if total_classes == 0:
            return 0

        max_bunkable = 0
        while (attended_classes / (total_classes + max_bunkable)) * 100 >= threshold:
            max_bunkable += 1
        return max_bunkable - 1 if max_bunkable > 0 else 0

    @staticmethod
    def calculate_threshold_mark(total_classes, threshold):
        """
        Calculate the minimum number of attended classes needed to meet the threshold.
        """
        return int((threshold / 100) * total_classes)
