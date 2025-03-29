class AttendanceCalculator:
    @staticmethod
    def calculate_bunkable(total_classes, attended_classes, threshold):
        """
        Calculate the maximum number of bunkable classes given the threshold.
        """
        if total_classes == 0:
            return 0

        max_bunkable = (attended_classes * 100 // threshold) - total_classes
        return max(0, max_bunkable)

    @staticmethod
    def calculate_threshold_mark(total_classes, threshold):
        """
        Calculate the minimum number of attended classes needed to meet the threshold.
        """
        return int((threshold / 100) * total_classes)
