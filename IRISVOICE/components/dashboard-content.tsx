'use client';

import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import { GlassRow } from './glass-row';

interface Activity {
  id: string;
  name: string;
  hasWarning?: string;
}

interface Lesson {
  id: string;
  name: string;
  activities: Activity[];
  expanded?: boolean;
}

interface Chapter {
  id: string;
  name: string;
  lessons: Lesson[];
  expanded?: boolean;
}

interface Unit {
  id: string;
  name: string;
  chapters: Chapter[];
  expanded?: boolean;
}

export function DashboardContent() {
  const [units, setUnits] = useState<Unit[]>([
    {
      id: '1',
      name: 'Unit 1',
      expanded: true,
      chapters: [
        {
          id: '1-1',
          name: 'Chapter 1',
          expanded: true,
          lessons: [
            {
              id: '1-1-1',
              name: 'Lesson 1',
              expanded: true,
              activities: [
                { id: 'a1', name: 'Activity 1 - 1' },
                { id: 'a2', name: 'Activity 1 - 2' },
              ],
            },
            {
              id: '1-1-2',
              name: 'Lesson 2',
              expanded: false,
              activities: [
                { id: 'a3', name: 'Activity 2 - 1' },
                { id: 'a4', name: 'Activity 2 - 2', hasWarning: 'Activity is missing content.' },
              ],
            },
          ],
        },
        {
          id: '1-2',
          name: 'Chapter 2',
          expanded: false,
          lessons: [
            {
              id: '1-2-1',
              name: 'Lesson 1',
              expanded: false,
              activities: [
                { id: 'a5', name: 'Activity 1 - 1', hasWarning: 'Activity is missing content.' },
              ],
            },
          ],
        },
      ],
    },
  ]);

  const toggleExpand = (
    type: 'unit' | 'chapter' | 'lesson',
    unitId: string,
    chapterId?: string,
    lessonId?: string
  ) => {
    setUnits((prev) =>
      prev.map((unit) => {
        if (unit.id !== unitId) return unit;
        if (type === 'unit') return { ...unit, expanded: !unit.expanded };
        return {
          ...unit,
          chapters: unit.chapters.map((chapter) => {
            if (chapter.id !== chapterId) return chapter;
            if (type === 'chapter') return { ...chapter, expanded: !chapter.expanded };
            return {
              ...chapter,
              lessons: chapter.lessons.map((lesson) =>
                lesson.id === lessonId ? { ...lesson, expanded: !lesson.expanded } : lesson
              ),
            };
          }),
        };
      })
    );
  };

  return (
    <div className="flex-1 overflow-auto p-8">
      {/* Title Section */}
      <div className="mb-8">
        <div className="flex items-center gap-4 mb-2">
          <h1 className="text-3xl font-semibold text-white">Classical Latin (Pilot)</h1>
          <span className="px-3 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-white/60 uppercase tracking-wider">
            Draft
          </span>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-200">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-sm">2 issues require attention.</span>
          </div>

          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-4 py-2 rounded-lg border border-white/10 text-white/70 hover:bg-white/5 transition-colors text-sm">
              <div className="w-2 h-2 rounded-full bg-emerald-400" />
              Ready for Review
            </button>
            <button className="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/15 text-white text-sm font-medium transition-colors border border-white/10">
              Save Course
            </button>
          </div>
        </div>
      </div>

      {/* Hierarchical Tree */}
      <div className="space-y-2">
        {units.map((unit) => (
          <div key={unit.id} className="space-y-2">
            <GlassRow
              level={0}
              label={unit.name}
              expanded={unit.expanded}
              onToggle={() => toggleExpand('unit', unit.id)}
              actions={['add', 'chevron', 'trash']}
            />

            {unit.expanded && (
              <div className="ml-8 space-y-2">
                {unit.chapters.map((chapter) => (
                  <div key={chapter.id}>
                    <GlassRow
                      level={1}
                      label={chapter.name}
                      expanded={chapter.expanded}
                      onToggle={() => toggleExpand('chapter', unit.id, chapter.id)}
                      actions={['add', 'chevron', 'trash']}
                    />

                    {chapter.expanded && (
                      <div className="ml-8 space-y-2">
                        {chapter.lessons.map((lesson) => (
                          <div key={lesson.id}>
                            <GlassRow
                              level={2}
                              label={lesson.name}
                              expanded={lesson.expanded}
                              onToggle={() => toggleExpand('lesson', unit.id, chapter.id, lesson.id)}
                              actions={['add', 'chevron', 'trash']}
                            />

                            {lesson.expanded && (
                              <div className="ml-8 space-y-2">
                                {lesson.activities.map((activity) => (
                                  <GlassRow
                                    key={activity.id}
                                    level={3}
                                    label={activity.name}
                                    actions={['edit', 'warning', 'trash']}
                                    warning={activity.hasWarning}
                                  />
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
