/* prodRanges — extracted from index.html for performance */
    var prodRanges = {
      QB: [
        { label: '30+ PPG', fn: p => p >= 30 },
        { label: '25-30', fn: p => p >= 25 && p < 30 },
        { label: '20-25', fn: p => p >= 20 && p < 25 },
        { label: '15-20', fn: p => p >= 15 && p < 20 },
        { label: '10-15', fn: p => p >= 10 && p < 15 },
        { label: '<10', fn: p => p < 10 }
      ],
      RB: [
        { label: '20+ PPG', fn: p => p >= 20 },
        { label: '16-20', fn: p => p >= 16 && p < 20 },
        { label: '12-16', fn: p => p >= 12 && p < 16 },
        { label: '8-12', fn: p => p >= 8 && p < 12 },
        { label: '<8', fn: p => p < 8 }
      ],
      WR: [
        { label: '18+ PPG', fn: p => p >= 18 },
        { label: '14-18', fn: p => p >= 14 && p < 18 },
        { label: '10-14', fn: p => p >= 10 && p < 14 },
        { label: '6-10', fn: p => p >= 6 && p < 10 },
        { label: '<6', fn: p => p < 6 }
      ],
      TE: [
        { label: '14+ PPG', fn: p => p >= 14 },
        { label: '10-14', fn: p => p >= 10 && p < 14 },
        { label: '7-10', fn: p => p >= 7 && p < 10 },
        { label: '4-7', fn: p => p >= 4 && p < 7 },
        { label: '<4', fn: p => p < 4 }
      ]
    };
