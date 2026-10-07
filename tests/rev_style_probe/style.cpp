// Derived from Data Pump test_rev_style.cpp; Copyright (c) 2026 mirage335.
// SPDX-License-Identifier: CC0-1.0; see COPYING and README.md.
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>

import Rev.Appearance;
import Rev.Core.DirtyFlag;

namespace {
void check(bool condition, const char* message) {
    if(!condition) throw std::runtime_error(message);
}
void equality() {
    using namespace Rev::Appearance;
    // Explicit aggregate initialization avoids GCC 15's module-import failure
    // for the implicit default constructor; the flag stays clean and lists empty.
    Rev::Core::DirtyFlag dirty{};
    auto distance=Px(12), same=Px(12);
    same.transition=250;same.dirty=&dirty;
    const auto fixed=Px(12);
    check(distance==same && same==distance && fixed==distance && distance==fixed,
          "distance equality must be symmetric and ignore notification/transition metadata");
    check(!(fixed==Px(13)) && !(fixed==Pct(12)), "distance equality lost its value or unit");
    check(Px(-0.f)==Px(0.f), "distance equality changed signed-zero semantics");
    auto nan=Px(std::numeric_limits<float>::quiet_NaN());
    check(!(nan==nan), "distance equality changed NaN semantics");
    same=distance;
    check(!dirty.isDirty() && same.dirty==&dirty && same.transition==250,
          "equal distance assignment changed existing notification/transition behavior");
    same=Px(13);
    check(dirty.isDirty() && same.dirty==&dirty && same.val==13,
          "changed distance assignment must retain and notify its owner");

    auto color=rgba(.1f,.2f,.3f,.4f), same_color=color;
    same_color.transition=100;same_color.dirty=&dirty;
    const auto fixed_color=color;
    check(color==same_color && same_color==color && fixed_color==color && color==fixed_color,
          "color equality must be symmetric and ignore notification/transition metadata");
    same_color.a=.5f;
    check(!(fixed_color==same_color), "color equality lost alpha");

    VisibilityStyle visible{Visibility::Visible}, same_visible{Visibility::Visible};
    same_visible.dirty=&dirty;
    const VisibilityStyle fixed_visible{Visibility::Visible};
    check(visible==same_visible && same_visible==visible && fixed_visible==visible && visible==fixed_visible,
          "visibility equality must be symmetric and ignore notification metadata");
    check(fixed_visible==Visibility::Visible && Visibility::Visible==fixed_visible &&
          !(fixed_visible==Visibility::Hidden), "visibility enum comparison changed");
}
void layout() {
    using namespace Rev::Appearance;
    auto before=Style::Null(), after=Style::Null();
    check(!after.layoutDiffers(before), "equal styles spuriously changed geometry");
    after.background.color=rgba(.1f,.2f,.3f,.4f);
    check(!after.layoutDiffers(before), "paint-only changes must not force relayout");
    after.size.width=Px(12);
    check(after.layoutDiffers(before), "a width change must force relayout");
    after.size.width=before.size.width;
    after.visibility=Visibility::Hidden;
    check(after.layoutDiffers(before), "a visibility change must force relayout");
}
}
int main(int argc, char** argv) {
    try {
        if(argc != 2) throw std::runtime_error("Choose equality or layout");
        const std::string_view which = argv[1];
        if(which == "equality") equality();
        else if(which == "layout") layout();
        else throw std::runtime_error("Unknown style scenario");
        std::cout << "Foundation Rev " << which << " assertions passed\n";
    }
    catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
